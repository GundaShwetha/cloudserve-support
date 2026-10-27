"""Optional model-assisted grounding check (PR-05) over review_sample.csv.

    python -m evaluation.judge --sample evaluation/results/validation_run/review_sample.csv

Adds a `model_judge_any_unsupported` column. This ASSISTS the two human assessors required by the
Evaluation Framework; it does not replace them. Requires a configured model provider.
"""
from __future__ import annotations

import argparse
import csv
import json

from src.config import Settings
from src.generate import _extract_json
from src.prompts import load_prompt
from src.provider import OpenAICompatibleProvider, ProviderError
from src.retrieve import Corpus


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", required=True)
    a = ap.parse_args(argv)
    s = Settings()
    if not s.api_key:
        raise SystemExit("No model provider key configured; the human review does not need one.")
    corpus = Corpus.load(s.docs_path)
    prompt = load_prompt("evaluation/PR-05_grounding_judge.md")
    prov = OpenAICompatibleProvider(s)
    rows = list(csv.DictReader(open(a.sample, encoding="utf-8")))
    for r in rows:
        passages = "\n".join(f'<passage id="{c}">{corpus.resolve(c).text}</passage>'
                             for c in r["citations"].split() if corpus.resolve(c))
        reply = "\n".join(f"{i}. {line}" for i, line in enumerate(r["reply"].splitlines(), 1))
        try:
            out = _extract_json(prov.complete([{"role": "system", "content": prompt.text},
                                               {"role": "user", "content": f"<passages>{passages}</passages>\n<reply>{reply}</reply>"}]))
            r["model_judge_any_unsupported"] = json.dumps(out.get("any_unsupported")) if out else "unparseable"
        except ProviderError as exc:
            r["model_judge_any_unsupported"] = f"error: {exc}"
    with open(a.sample, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"judged {len(rows)} replies -> {a.sample}")


if __name__ == "__main__":
    main()
