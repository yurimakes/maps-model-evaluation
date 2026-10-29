# -*- coding: utf-8 -*-
"""Azure OpenAI 호출 부품 (임베딩 + 답변). 한도(분당 토큰·요청 수)를 스스로 지키며 부른다.

쉬운 설명
- 이 리소스는 한도가 작다: 답변 모델은 분당 토큰·요청 수 제한, 임베딩은 10초에 3번 제한이 있다.
- 그래서 '한도를 넘기 전에 스스로 기다리는 장치(Throttle)'를 둔다. 429(한도 초과)가 와도 알려 준 시간만큼 기다렸다 다시 보낸다.
- 모델이 어떤 옵션(reasoning_effort, response_format)을 거부하면 그 옵션만 빼고 다시 보낸다.
- 키는 코드에 적지 않는다. 호출하는 쪽이 넘겨 준다(Databricks 비밀 보관함에서 읽음).
"""
import json
import re
import time
import requests

API_VERSION = "2025-04-01-preview"


class Throttle:
    """최근 60초 동안 쓴 토큰·요청 수를 세어, 넘을 것 같으면 기다린다."""

    def __init__(self, tokens_per_min, reqs_per_min=None, reqs_per_10s=None):
        self.tpm = tokens_per_min
        self.rpm = reqs_per_min
        self.r10 = reqs_per_10s
        self.events = []  # (시각, 토큰)

    def _trim(self, now):
        self.events = [e for e in self.events if now - e[0] < 60]

    def wait(self, need_tokens):
        while True:
            now = time.time()
            self._trim(now)
            used = sum(t for _, t in self.events)
            n60 = len(self.events)
            n10 = sum(1 for ts, _ in self.events if now - ts < 10)
            waits = []
            if self.tpm and used + need_tokens > self.tpm and self.events:
                waits.append(60 - (now - self.events[0][0]) + 0.3)
            if self.rpm and n60 >= self.rpm:
                waits.append(60 - (now - self.events[0][0]) + 0.3)
            if self.r10 and n10 >= self.r10:
                ts10 = [ts for ts, _ in self.events if now - ts < 10]
                waits.append(10 - (now - min(ts10)) + 0.3)
            if not waits:
                return
            time.sleep(max(0.5, min(max(waits), 65)))

    def add(self, tokens):
        self.events.append((time.time(), tokens))


def est_tokens(text):
    """한글 섞인 글은 글자 수의 약 0.5배로 잡는다(실측: 임베딩 글 0.71, 답변 질문 0.4~0.5)(실제 사용량은 응답에서 다시 세어 한도 계산에 쓴다)."""
    return int(len(text) * 0.5) + 8


class AzureClient:
    def __init__(self, endpoint, key, chat_deployment="gpt-5.4-nano-deploy",
                 embed_deployment="text-embedding-3-small-deploy",
                 chat_tpm=3000, chat_rpm=3, embed_tpm=3000, embed_r10=3,
                 temperature=None, seed=None, log=print):
        self.endpoint = endpoint.rstrip("/")
        self.key = key
        self.chat_dep = chat_deployment
        self.embed_dep = embed_deployment
        self.chat_thr = Throttle(chat_tpm, reqs_per_min=chat_rpm)
        self.embed_thr = Throttle(embed_tpm, reqs_per_10s=embed_r10)
        self.temperature = temperature  # 지정하면(예: 0) 모든 chat 호출에 고정값으로 실림
        self.seed = seed                # 지정하면 모든 chat 호출에 고정값으로 실림
        self.calls = []  # 호출 기록(성공·실패 모두)
        self.log = log
        self._drop = set()  # 모델이 거부해서 빼기로 한 옵션

    # ---------- 공통 ----------
    def _url(self, dep, op):
        return f"{self.endpoint}/openai/deployments/{dep}/{op}?api-version={API_VERSION}"

    def _post(self, dep, op, body, thr, need, kind):
        headers = {"api-key": self.key, "Content-Type": "application/json"}
        last = None
        for attempt in range(8):
            thr.wait(need)
            t0 = time.time()
            try:
                r = requests.post(self._url(dep, op), headers=headers, json=body, timeout=180)
            except requests.RequestException as e:
                last = f"연결 오류: {e}"
                self.calls.append({"kind": kind, "ok": False, "status": "EXC", "sec": round(time.time() - t0, 1), "note": last[:200]})
                time.sleep(min(5 * (attempt + 1), 30))
                continue
            sec = round(time.time() - t0, 1)
            if r.status_code == 200:
                data = r.json()
                usage = data.get("usage") or {}
                used = usage.get("total_tokens") or need
                thr.add(used)
                self.calls.append({"kind": kind, "ok": True, "status": 200, "sec": sec,
                                   "prompt_tokens": usage.get("prompt_tokens"),
                                   "completion_tokens": usage.get("completion_tokens"), "note": ""})
                return data
            last = f"{r.status_code} {r.text[:300]}"
            self.calls.append({"kind": kind, "ok": False, "status": r.status_code, "sec": sec, "note": r.text[:200]})
            if r.status_code == 429:
                ra = r.headers.get("Retry-After") or re.findall(r"retry after (\d+)", r.text)
                ra = ra if isinstance(ra, str) else (ra[0] if ra else "20")
                wait = float(ra) + 1
                self.log(f"  ⏳ 한도 초과(429) → {wait:.0f}초 기다렸다 다시 보냅니다")
                thr.add(need)  # 이미 쓴 것으로 치고 계산
                time.sleep(min(wait, 70))
                continue
            if r.status_code >= 500:
                time.sleep(min(5 * (attempt + 1), 40))
                continue
            if r.status_code == 400:
                bad = self._unsupported(r.text, body)
                if bad:
                    self.log(f"  ℹ 이 모델이 '{bad}' 옵션을 받지 않아 빼고 다시 보냅니다")
                    self._drop.add(bad)
                    body.pop(bad, None)
                    continue
            raise RuntimeError(f"Azure 호출 실패: {last}")
        raise RuntimeError(f"Azure 호출을 여러 번 다시 해도 실패: {last}")

    @staticmethod
    def _unsupported(text, body):
        for opt in ("reasoning_effort", "response_format", "temperature", "seed", "max_completion_tokens"):
            if opt in body and opt in text:
                return opt
        return None

    # ---------- 임베딩 ----------
    def embed_batched(self, texts, batch_tokens=1800, on_batch=None):
        """texts → 벡터 목록. 분당 토큰 한도에 맞춰 묶음으로 보낸다."""
        out = [None] * len(texts)
        i = 0
        while i < len(texts):
            batch, tok, idx = [], 0, []
            while i < len(texts):
                t = est_tokens(texts[i][:6000])
                if batch and tok + t > batch_tokens:
                    break
                batch.append(texts[i][:6000]); idx.append(i); tok += t; i += 1
            data = self._post(self.embed_dep, "embeddings", {"input": batch}, self.embed_thr, tok, "embed")
            for j, d in zip(idx, sorted(data["data"], key=lambda x: x["index"])):
                out[j] = d["embedding"]
            if on_batch:
                on_batch(i, len(texts))
        return out

    # ---------- 답변 ----------
    def chat(self, messages, max_completion_tokens=1200, json_mode=True, reasoning_effort="minimal"):
        need = sum(est_tokens(m["content"]) for m in messages) + max_completion_tokens
        cur = max_completion_tokens
        for _ in range(3):
            body = {"messages": messages, "max_completion_tokens": cur}
            if json_mode and "response_format" not in self._drop:
                body["response_format"] = {"type": "json_object"}
            if reasoning_effort and "reasoning_effort" not in self._drop:
                body["reasoning_effort"] = reasoning_effort
            if self.temperature is not None and "temperature" not in self._drop:
                body["temperature"] = self.temperature
            if self.seed is not None and "seed" not in self._drop:
                body["seed"] = self.seed
            data = self._post(self.chat_dep, "chat/completions", body, self.chat_thr, need, "chat")
            ch = (data.get("choices") or [{}])[0]
            text = (ch.get("message") or {}).get("content") or ""
            if text.strip():
                return text, data.get("usage") or {}
            cur = cur * 2  # 빈 답이면(생각하느라 토큰을 다 씀) 토큰을 두 배로 늘려 다시
            need = sum(est_tokens(m["content"]) for m in messages) + cur
            self.log(f"  ℹ 빈 답 → 답변 토큰 한도를 {cur}로 늘려 다시 보냅니다")
        return "", {}


def parse_json(text):
    """답변에서 JSON 부분만 꺼낸다(앞뒤 설명·```json 울타리가 붙어도 처리)."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(t[a:b + 1])
        except Exception:
            return None
    return None
