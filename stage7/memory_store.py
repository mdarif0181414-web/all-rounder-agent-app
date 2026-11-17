"""Long-term memory store — একই interface-এর দুটি backend:

- SupabaseStore: আসল ব্যবস্থা। Supabase (Postgres + pgvector) REST API দিয়ে
  memories table-এ জমা ও match_memories function দিয়ে similarity search।
- LocalStore: পরীক্ষার জন্য local JSON file + হাতে-হিসাব cosine similarity।
  Interface হুবহু এক — তাই backend বদলালেও agent-এর code বদলায় না।

দুই জায়গাতেই ফলাফলের গঠন এক: [{id, content, source, similarity}, ...]
"""
import json
import math
import os

import requests


def _cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class LocalStore:
    name = "local"

    def __init__(self, path: str):
        self.path = path
        self.rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.rows = json.load(f)

    def add(self, content: str, source: str, embedding: list) -> int:
        rid = (self.rows[-1]["id"] + 1) if self.rows else 1
        self.rows.append({"id": rid, "content": content, "source": source,
                          "embedding": embedding})
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.rows, f, ensure_ascii=False)
        return rid

    def search(self, query_embedding: list, limit: int = 5) -> list:
        scored = [{"id": r["id"], "content": r["content"], "source": r["source"],
                   "similarity": _cosine(query_embedding, r["embedding"])}
                  for r in self.rows]
        scored.sort(key=lambda x: -x["similarity"])
        return scored[:limit]

    def count(self) -> int:
        return len(self.rows)


class SupabaseStore:
    name = "supabase"

    def __init__(self, url: str, service_key: str):
        self.base = url.rstrip("/")
        self.headers = {"apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                        "Content-Type": "application/json"}

    def add(self, content: str, source: str, embedding: list) -> int:
        r = requests.post(
            f"{self.base}/rest/v1/memories",
            headers={**self.headers, "Prefer": "return=representation"},
            json={"content": content, "source": source, "embedding": embedding},
            timeout=30)
        r.raise_for_status()
        return r.json()[0]["id"]

    def search(self, query_embedding: list, limit: int = 5) -> list:
        r = requests.post(
            f"{self.base}/rest/v1/rpc/match_memories",
            headers=self.headers,
            json={"query_embedding": query_embedding, "match_count": limit},
            timeout=30)
        r.raise_for_status()
        return [{"id": row["id"], "content": row["content"],
                 "source": row["source"],
                 "similarity": float(row["similarity"])} for row in r.json()]

    def count(self) -> int:
        r = requests.get(
            f"{self.base}/rest/v1/memories?select=id",
            headers={**self.headers, "Prefer": "count=exact",
                     "Range": "0-0"},
            timeout=30)
        r.raise_for_status()
        return int(r.headers.get("content-range", "*/0").split("/")[-1])


def open_store(local_path: str):
    """SUPABASE_URL + SUPABASE_SERVICE_KEY env থাকলে আসল store, নইলে local।"""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and key:
        return SupabaseStore(url, key)
    return LocalStore(local_path)
