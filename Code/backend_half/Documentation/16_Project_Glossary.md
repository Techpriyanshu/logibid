# 16 — Project Glossary

> Dictionary of LogiBid words. Keep this open while reading other docs.

---

## A–D

| Term | Meaning |
|---|---|
| **API** | A URL the frontend calls to ask the backend for data or actions |
| **Automation** | Code that controls Chrome and does bidding without manual typing |
| **Bid** | An offer amount entered for a transport opportunity |
| **Bid amount** | The number typed into SAP for a row |
| **Bid outcomes** | Historical finished results used for reports |
| **Chrome instance** | One running Chrome browser window/process controlled by Selenium |
| **Control Panel** | Screen where vendor starts bidding |
| **CORS** | Browser security rule; backend must allow frontend origin |
| **Depot** | A location/node in the cement network (Ayodhya, Lucknow, …) |
| **Desired bid** | What the vendor wants to chase (quantity + optional destination + depot) |

## E–L

| Term | Meaning |
|---|---|
| **e-Bidding** | Online competitive bidding portal process |
| **Execution** | Stage where automation types and saves bid amounts |
| **Expires In** | SAP timer text meaning bidding window is ending |
| **Fleet** | Truck operations side of the business |
| **Fleet request** | Ask vendor to pause/close a live leg |
| **Job** | One Start Bid run that may include many depots |
| **job_id** | Unique id for a job; stored in sessionStorage for UI |
| **Leg** | One live desired-bid line inside a job |
| **Live bids** | Current operational status rows |

## M–R

| Term | Meaning |
|---|---|
| **Monitoring** | Repeatedly checking the portal for matching opportunities |
| **Multiprocess** | One OS process (and Chrome) per depot |
| **Notification** | Alert row for users |
| **Observer** | Background logic that watches DBs and copies/creates derived data |
| **Orchestrator** | Code that launches and manages depot workers |
| **Outcome** | Historical result record (won/lost/stopped/failed…) |
| **Planning** | Deciding which rows match and what amounts to prepare |
| **Polling** | UI asks the API again and again for updates |
| **ProcessPoolExecutor** | Python tool that runs functions in separate processes |
| **Rank** | Position of your bid (1 is best/win in this system) |

## S–Z

| Term | Meaning |
|---|---|
| **SAP Fiori / Eye2Serve** | The vendor portal website being automated |
| **Selenium** | Library that controls browsers for automation |
| **SessionStorage** | Browser storage for current tab session (holds active job id) |
| **SQLite** | Database stored as a file |
| **Start Bid** | Button that begins automation |
| **Start In** | SAP timer text meaning bidding will start soon |
| **Stagger** | Intentional delay between launching depot workers (210 seconds) |
| **Successful bid** | Saved Rank-1 win record |
| **Truck Master** | Registry of trucks and documents |
| **User control** | active / paused / stopped flag for a live leg |
| **Vendor** | Role that starts bids and can approve fleet requests |
| **WAL** | SQLite mode that helps concurrent readers/writers |
| **Worker** | One process handling one depot |

---

## Confusable pairs

| Don’t confuse | Difference |
|---|---|
| Job vs Worker | Job = whole Start Bid; Worker = one depot process |
| Live bids vs Outcomes | Live = now; Outcomes = history for reports |
| Successful bids vs Outcomes | Successful = Rank-1 trophy list; Outcomes = broader history |
| Pause vs Stop | Pause can resume; Stop ends that leg’s participation |
| Monitoring vs Polling | Monitoring = engine watches SAP; Polling = UI watches API |

---

Next: [17_Debugging_Guide.md](17_Debugging_Guide.md)
