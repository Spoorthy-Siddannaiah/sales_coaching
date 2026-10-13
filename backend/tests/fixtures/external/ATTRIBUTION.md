# External evaluation fixture

Source: [Thomasgudan/kapibala-sales-dialogues](https://huggingface.co/datasets/Thomasgudan/kapibala-sales-dialogues), published by Thomasgudan.
Revision: `1e253feba79aaabdd9d5ea14586608b5002d84f3`, retrieved 2026-10-09.
Record: `kapibala-sim:mstate:S46_standard`; source files `data/conversations.jsonl` and `data/meta.jsonl`.

License: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/), as declared in the dataset card. Redistribution is permitted with attribution, license link and disclosure of changes. No endorsement is implied.

The dataset card describes fully synthetic LLM-simulated customers and AI salespeople. This is **not an authentic recorded call** and is independent of our Codex-authored synthetic fixture.
The published role mapping is `a` = salesperson, `b` = customer. This record has 15 messages, English B2B software, OmniSupport AI Enterprise Tier.

Message contents, ordering and role values in `kapibala_record.json` are unchanged. Only JSON whitespace formatting differs. `kapibala_metadata.json` preserves the corresponding published metadata. Evaluation serialization adds readable labels and newline separators; it does not rewrite, extend or split source messages. A customer message merges several simulated exchanges upstream; this limitation is retained.

Selection: substantive systems-discovery question, order tracking/returns needs, SOC2/encryption prerequisite (a security objection), annual pricing and kickoff discussion. The synthetic customer's claimed purchase is evidence of a claim within this dialogue, not an independently verified sale.
