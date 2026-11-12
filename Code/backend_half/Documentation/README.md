# LogiBid Documentation — Start Here

Welcome! This folder is a **learning guide** for new team members.

You do **not** need to memorize everything on day one.  
Read the documents **in order**. Each one builds on the previous ones.

---

## How to use these docs

1. Start with **01** (what the product is).
2. Then **02** (where files live).
3. Then **03** (the full story from button click to report).
4. After that, go deeper into backend, automation, databases, APIs, and frontend.
5. Keep **16_Project_Glossary.md** open while reading — it explains project words.

---

## Document index

| # | File | What you learn |
|---|---|---|
| 01 | [01_Project_Overview.md](01_Project_Overview.md) | What LogiBid is and why it exists |
| 02 | [02_Folder_Structure.md](02_Folder_Structure.md) | Where every important folder lives |
| 03 | [03_Complete_System_Flow.md](03_Complete_System_Flow.md) | Full lifecycle from UI to reports |
| 04 | [04_Backend_Architecture.md](04_Backend_Architecture.md) | How the FastAPI backend works |
| 05 | [05_Automation_Architecture.md](05_Automation_Architecture.md) | How Chrome bidding automation works |
| 06 | [06_File_by_File_Explanation.md](06_File_by_File_Explanation.md) | Important backend files explained |
| 07 | [07_Function_by_Function_Guide.md](07_Function_by_Function_Guide.md) | Important functions explained |
| 08 | [08_Database_Guide.md](08_Database_Guide.md) | All SQLite databases |
| 09 | [09_API_Guide.md](09_API_Guide.md) | All main APIs in plain English |
| 10 | [10_Frontend_Architecture.md](10_Frontend_Architecture.md) | How the React UI works |
| 11 | [11_Frontend_File_Guide.md](11_Frontend_File_Guide.md) | Important frontend files |
| 12 | [12_Control_Panel_Flow.md](12_Control_Panel_Flow.md) | What happens after Start Bid |
| 13 | [13_Live_Bidding_Flow.md](13_Live_Bidding_Flow.md) | Live statuses and transitions |
| 14 | [14_Reports_Architecture.md](14_Reports_Architecture.md) | How reports are built |
| 15 | [15_Notifications_Architecture.md](15_Notifications_Architecture.md) | How notifications appear |
| 16 | [16_Project_Glossary.md](16_Project_Glossary.md) | Dictionary of project terms |
| 17 | [17_Debugging_Guide.md](17_Debugging_Guide.md) | How to debug safely |
| 18 | [18_Project_FAQ.md](18_Project_FAQ.md) | Common “why?” questions |

---

## Codebase locations

| Part | Path |
|---|---|
| Backend + Automation | `C:\Users\DELL\Desktop\backend_parallel_code_COPT_EDITS_IMPROVED - Copy_FORTRIAL_SPI - Copy` |
| Frontend (LogiBid UI) | `C:\Users\DELL\Desktop\frontend_latest` |

---

## Important safety note

The **automation engine** (browser bidding) is the heart of the system.

Do **not** casually edit these files unless a senior engineer asks you to:

- `depot_bidding_engine.py`
- `parallel_orchestrator.py`
- `selenium_worker.py`
- `live_status.py`
- `live_bids_store.py`
- `successful_bids_store.py`

---

## Suggested first week reading plan

| Day | Read |
|---|---|
| Day 1 | 01 + 02 + 16 |
| Day 2 | 03 + 12 |
| Day 3 | 04 + 08 |
| Day 4 | 05 + 13 |
| Day 5 | 09 + 10 + 11 |
| Day 6 | 14 + 15 |
| Day 7 | 06 + 07 + 17 + 18 |

Happy learning!
