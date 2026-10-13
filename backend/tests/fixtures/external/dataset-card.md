---
license: cc-by-4.0
language:
  - zh
  - en
task_categories:
  - text-classification
  - text-generation
tags:
  - sales
  - dialogue
  - synthetic
  - customer-intent
pretty_name: Kapibala Sales Dialogues
size_categories:
  - n<1K
configs:
  - config_name: conversations
    data_files: data/conversations.jsonl
    default: true
  - config_name: meta
    data_files: data/meta.jsonl
  - config_name: labels_L1_outcome
    data_files: data/labels_L1_outcome.jsonl
  - config_name: labels_L2_conversation
    data_files: data/labels_L2_conversation.jsonl
  - config_name: labels_L3_turns
    data_files: data/labels_L3_turns.jsonl
  - config_name: conversations_L1
    data_files: data/with_text/conversations_L1.jsonl
  - config_name: conversations_L2
    data_files: data/with_text/conversations_L2.jsonl
  - config_name: conversations_L3
    data_files: data/with_text/conversations_L3.jsonl
  - config_name: extras_audit30_deepseek_replay
    data_files: extras/audit30_deepseek_replay.jsonl
  - config_name: extras_l3_rubric_v2
    data_files: extras/l3_rubric_v2_baseline_talksub_loop.jsonl
  - config_name: extras_l3_live_labels
    data_files: extras/l3_live_labels_mstate_mboth.jsonl
  - config_name: extras_l3_audit30
    data_files: extras/l3_audit30_talksub_signals_taxonomy.jsonl
---

# Kapibala Sales Dialogues

**A sales-conversation dataset with outcome, conversation-level and sentence-level labels**

[🤗 Hugging Face](https://huggingface.co/datasets/Thomasgudan/kapibala-sales-dialogues) · [Annotation details](docs/annotation.md) · [中文](README.zh.md)

630 synthetic sales conversations (11,688 messages, Chinese and English, five domains) between an LLM-simulated customer and an AI salesperson. Every conversation carries three layers of labels, each produced by a single method across the whole dataset:

- **L1 — outcome.** Did the customer buy, agree to a next step, stay undecided, or decline?
- **L2 — conversation.** A conversation-quality score and all 128 conversation-level features of *talksub*, a production conversation analyser.
- **L3 — sentence.** For every message: sentiment; for customers, purchase intent, stance, decision stage, emotion, aspect-level opinions, commitment and risk; for salespeople, 20 sales-practice behaviours.

The layers are designed to be checked against each other: does the analyser (L2) predict the outcome (L1)? Does it agree with what was actually said (L3)? Which salesperson behaviours (L3) come before a sale (L1)?

<p align="center"><img src="assets/structure.png" width="760" alt="Dataset structure"></p>

## Contents

1. [At a glance](#at-a-glance)
2. [Quick start](#quick-start)
3. [Data format](#data-format)
4. [How the conversations were made](#how-the-conversations-were-made)
5. [Annotation](#annotation)
6. [Validation](#validation)
7. [Statistics](#statistics)
8. [Limitations](#limitations)
9. [Reproducing the dataset](#reproducing-the-dataset)

## At a glance

| | |
|---|---|
| Conversations | 630 — 600 simulated (4 experimental arms × 150) + 30 expanded from SalesLLM-10k |
| Messages | 11,688 (3–70 per conversation, median 17); strictly alternating, customer first |
| Languages | 330 Chinese, 300 English |
| Domains | financial 148 · consumer 122 · real estate 120 · education 120 · B2B software 120 |
| L1 | 630 / 630 conversations |
| L2 | 630 / 630 conversations × 130 label columns |
| L3 | 11,688 / 11,688 messages × 32 label columns |
| Privacy | fully synthetic; no real customer data |
| License | CC BY 4.0 |

## Quick start

### Python reader

[`sales_dialogues.py`](sales_dialogues.py) is a single-file reader (standard library only; pandas for tables). It puts each conversation's text, meta and all three label layers into one object.

```python
from sales_dialogues import load

ds = load()                                        # from a clone; or load(repo="Thomasgudan/kapibala-sales-dialogues")
conv = ds["kapibala-sim:mboth:S36_standard"]

conv.outcome                                       # L1: 'next_step'
conv.feature("final.final_v22.cds_v22.score")      # L2: any of the 130 columns
for m in conv.customer_messages():                 # L3: labels on every message
    print(m.turn, m.content[:40], m.L3["intent"], m.L3["emotion"], m.L3["opinions"])

subset = ds.filter(arm="mboth", language="en", outcome=["bought", "next_step"])
per_conversation = ds.frame("conversations")      # pandas: meta + L1 + L2, 630 rows
per_message      = ds.frame("messages")           # pandas: text + meta + L3, 11,688 rows
```

| Object | Main members |
|---|---|
| `SalesDialogues` | `len(ds)`, `ds[id]` / `ds[i]`, iteration, `ids`, `filter(predicate, outcome=…, **meta)`, `messages()`, `frame("conversations" \| "messages")`, `to_board(url)` |
| `Conversation` | `id`, `meta`, `L1`, `L2`, `messages`, `outcome`, `feature(path)`, `talksub(prefix)`, `customer_messages()`, `salesperson_messages()`, `transcript(labels)` |
| `Message` | `turn`, `role` (`b` / `a`), `speaker`, `content`, `L3` |

From the command line:

```bash
python sales_dialogues.py info                                      # counts by source, arm, language, outcome
python sales_dialogues.py show kapibala-sim:mboth:S36_standard      # transcript with L1, key L2 and per-message L3
```

When using the Hugging Face copy, download the reader with `hf_hub_download("Thomasgudan/kapibala-sales-dialogues", "sales_dialogues.py", repo_type="dataset")`.

### Hugging Face `datasets`

```python
from datasets import load_dataset

repo = "Thomasgudan/kapibala-sales-dialogues"
convs = load_dataset(repo, "conversations_L3", split="train")   # text + sentence-level labels

for m in convs[0]["messages"][:4]:
    print(m["role"], m["content"][:40], m["L3"]["sentiment"], m["L3"]["intent"], m["L3"]["pressure"])
```

Every file below is a separate config (`load_dataset(repo, "<config>")`), and no login is needed.

### Browsing in the corpus board

The dataset can be loaded into `kcorpusd`, the corpus collector of kAgent, and browsed with its Streamlit board. Each conversation appears with its message timeline; every L3 label is a message-level field and every meta, L1 and L2 value a conversation-level field, named `dataset.<layer> | <column>` (e.g. `dataset.L3 | intent`, `dataset.L2 | final.final_v22.cds_v22.score`).

```bash
# 1. a kcorpusd on an empty database
createdb kcorpus_dataset
KCORPUS_DATABASE_URL=postgres://localhost/kcorpus_dataset ./bin/kcorpusd migrate
KCORPUS_DATABASE_URL=postgres://localhost/kcorpus_dataset KCORPUS_HTTP_ADDR=127.0.0.1:8788 ./bin/kcorpusd serve

# 2. push conversations and labels (safe to repeat)
python sales_dialogues.py board --url http://127.0.0.1:8788                 # all 630
python sales_dialogues.py board --url http://127.0.0.1:8788 --arm mboth --limit 20

# 3. fold the intake into the corpus, then open the board (view: 会话)
KCORPUS_DATABASE_URL=postgres://localhost/kcorpus_dataset ./bin/kcorpusd assemble
KCORPUS_URL=http://127.0.0.1:8788 streamlit run board/app.py
```

The same push is available in Python as `ds.to_board(url, team="sales-dialogues", layers=("meta", "L1", "L2", "L3"))`. Message timestamps in the board are synthetic (one minute apart), since the dataset has none.

## Data format

The labels are published in two equivalent shapes.

**Conversations with labels attached** (`data/with_text/`) — one row per conversation, for reading and modelling:

| Config | Row |
|---|---|
| `conversations_L1` | `{id, messages: [{role, content}], L1: {...}}` |
| `conversations_L2` | `{id, messages: [{role, content}], L2: {...}}` |
| `conversations_L3` | `{id, messages: [{role, content, L3: {...}}]}` — every message carries its own labels |

**Label tables** (`data/`) — flat columns joined on `id` (and `turn` for L3), for analysis:

| Config | One row per | Columns |
|---|---|---|
| `conversations` | conversation | `id`, `messages` |
| `meta` | conversation | `source`, `arm`, `language`, `domain`, `product`, `salesperson_type`, `customer_buy_propensity`, `difficulty`, `setting_id`, `ended`, `n_messages` |
| `labels_L1_outcome` | conversation | `outcome`, `bought`, `customer_intent`, `reason`, `method` (+ `manual_outcome`, `manual_evidence` for the 30 SalesLLM conversations) |
| `labels_L2_conversation` | conversation | `judge.quality`, `judge.quality_samples`, 128 talksub feature columns, `talksub_run.*` |
| `labels_L3_turns` | message | `turn`, `role`, 4 sentiment columns, 8 customer columns, 20 salesperson columns |

`role` is `b` for the customer and `a` for the salesperson; `turn` is the index into `messages`. Consecutive messages from the same speaker are joined with a newline, so turns strictly alternate.

An L3 message looks like this (customer turn, abridged):

```json
{"role": "b",
 "content": "您好，我想咨询一下，咱们银行有没有那种既可以随时取用钱，收益又比普通活期高一点……",
 "L3": {"sentiment": 0.30, "intent": 7, "stance": "question", "reaction": "same", "stage": "explore",
        "emotion": "neutral", "commitment": "none", "risk": "none",
        "opinions": [{"aspect": "fit", "polarity": "positive", "new": true, "topic": "寻找灵活高息"},
                     {"aspect": "trust", "polarity": "positive", "new": true, "topic": "资金安全保障"}]}}
```

Field-level definitions are in [`data/schema.json`](data/schema.json); the 128 talksub features, with types and observed values, are in [`data/talksub_features.json`](data/talksub_features.json).

## How the conversations were made

| Source | Arm | n | Setup |
|---|---|---|---|
| Simulated | `baseline` | 150 | 50 scripts adapted from SalesLLM × 3 salesperson styles (standard, pushy, passive). The customer is played by an LLM following the script; the salesperson is Kapibala's reply model, with no conversation state. |
| Simulated | `talksub_loop` | 150 | Same scripts; talksub analyses the conversation every 10 messages and its output is passed to the salesperson model. |
| Simulated | `mstate` | 150 | Same scripts; every customer message is labelled live and summarised into a state passed to the salesperson model. |
| Simulated | `mboth` | 150 | As `mstate`, plus three candidate replies per turn, selected or blocked by pressure and responsiveness. |
| SalesLLM | — | 30 | Conversations sampled from SalesLLM-10k and expanded to 60–70 messages (Chinese). |

Scripts cover financial products, consumer goods, real estate, education and B2B software; the simulated arms are half Chinese, half English.

## Annotation

Full definitions, prompts and per-column results: [docs/annotation.md](docs/annotation.md).

**L1 — outcome.** An LLM judge reads the whole conversation and assigns one of `bought` (clear commitment to buy), `next_step` (agreed to a concrete next step), `undecided` or `declined`, plus the customer's final intent (0–10) and a one-sentence reason. The 30 SalesLLM conversations also have a human-read outcome under a stricter definition (payment or order completed inside the conversation).

**L2 — conversation.**
- `judge.quality` — the SalesLLM paper's conversation-quality prompt (how much the salesperson advanced the deal, 0–10), mean of three samples.
- 128 talksub features — talksub's full conversation-level output, run once at the end of every conversation with one configuration: 30 free-text fields (summary, customer insight, profile, risk), 18 raw model judgements, 23 rule-stabilised states (trust, tone, stage, concerns, recommended action, risk) and 57 KPI fields across 15 indicators (conversion readiness, CDS, HRI, stage fit, trust, PCS, …). Column names are talksub contract paths, e.g. `final.final_v22.cds_v22.score`.

**L3 — sentence.** An independent reference annotation, not derived from talksub.
- Sentiment for every message from a multilingual sentiment model (score in [−1, 1] and class probabilities).
- A sales-practice rubric applied by an LLM that sees the whole conversation and the product sheet:
  - *customer* — `intent` (0–10), `stance`, `reaction` (warmer / same / cooler), `stage`, `emotion`, `opinions` (aspect, polarity, new?), `commitment`, `risk`;
  - *salesperson* — credibility and social proof; discovery (SPIN question type, key elements asked); value presentation (benefit level, need reference, framing, volunteered negatives, decisiveness, vivid description, factual consistency); objection handling (acknowledge, clarify, respond, confirm, reframe); advancing (advance type, pressure 0–3); responsiveness (answered, defer).

Where talksub has the same concept, L3 uses talksub's value sets (`stage`, `emotion`, `commitment`, `risk`, opinion aspects), so the two layers can be compared directly.

## Validation

| Check | Result |
|---|---|
| L2 values vs raw analyser output | all 80,640 values (630 × 128) identical |
| L3 rubric vs a stronger model (same prompt, 30 conversations, 802 turns) | κ ≥ 0.75 for intent (0.93), pressure (0.88), SPIN question type (0.81), defer (0.79), social proof (0.79), benefit level (0.78), stance (0.77), decisiveness (0.76); 0.5–0.75 for 13 more columns; below 0.5 for `commitment`, `risk`, `framing`, `factual`, `reframe`, `confirm` |
| L3 rubric vs the previous rubric version (2,498 customer / 2,203 salesperson turns) | intent κw 0.93, pressure 0.86, benefit level 0.83 |
| L3 vs L1 (Spearman with outcome, 630 conversations) | final customer intent 0.86 · mean customer sentiment 0.59 · number of negative opinions −0.47 |
| L1 judge vs human (30 SalesLLM conversations) | 15/30 agree (κ 0.36); 11 of the 15 disagreements are verbal commitments ("I'll go and order now") that the judge counts as `bought` and the human, under the stricter definition, as `next_step` |

Per-column agreement is in [`data/l3_reliability.json`](data/l3_reliability.json).

## Statistics

| Group | Mean messages | bought / next_step / undecided / declined | Mean judge quality |
|---|---|---|---|
| baseline | 15.9 | 26 / 56 / 10 / 58 | 3.37 |
| talksub_loop | 15.6 | 23 / 76 / 6 / 45 | 3.27 |
| mstate | 16.6 | 26 / 68 / 8 / 48 | 3.67 |
| mboth | 16.8 | 23 / 76 / 13 / 38 | 3.46 |
| SalesLLM | 65.0 | 17 / 3 / 2 / 8 | 7.61 |

| Salesperson style (simulated, 200 each) | bought | declined | Mean judge quality |
|---|---|---|---|
| standard | 35 | 51 | 4.36 |
| pushy | 38 | 51 | 4.17 |
| passive | 25 | 87 | 1.80 |

Differences between arms are small relative to their size (150 each) and outcomes are LLM-judged; they should not be read as a ranking of strategies.

## Limitations

- **Simulated customers.** LLM customers walk away less often and are easier to persuade than real ones; conclusions about outcomes need confirming on real conversations.
- **Model-produced labels.** L1, the quality score and the L3 rubric come from Gemini models, the same family that plays the customer. The L3 rubric uses a lightweight model; six columns agree only weakly with a stronger model (see [Validation](#validation)), and `clarify` / `confirm` are almost never positive.
- **What `bought` means.** L1 counts a clear verbal commitment as `bought`; it does not require a completed payment.
- **Analyser scope.** talksub analyses at most the last 20 extracted messages, so for 420 longer conversations L2 reflects their final part. Timestamps are simulated, so time-based talksub indicators reflect replay pacing. Eight talksub features are always null in this run (trust trends, deal details).
- **Text normalisation.** Multi-bubble replies are merged, and messages where the salesperson model chose not to reply are dropped.

## Reproducing the dataset

`build_unified.py` rebuilds `data/` and `extras/` from the raw experiment outputs, which are not included in this repository:

```bash
KAPIBALA_ROOT=/path/to/raw python build_unified.py
```

The reader is [`sales_dialogues.py`](sales_dialogues.py). The labelling scripts are in [`pipeline/`](pipeline/): `talksub_eval_arm.mjs` (L2 analyser run), `llm_annotate_v3.py` (L3 rubric), `sentiment_v3.py` (L3 sentiment). `extras/` keeps earlier labels that cover only part of the data (the previous rubric version, the live labels used inside the `mstate` / `mboth` experiments, and the original SalesLLM audit annotations); see [docs/annotation.md](docs/annotation.md#extras). `pipeline/` also holds the build inputs, and `tools/` the scripts that draw the diagram, generate the repository front page and the Hugging Face card from this README, and re-check the published files (`python tools/validate.py`).
