# Thief Agent ג€” Distributed Cops-and-Robbers over P2P

**Group:** Hassarma-Agents (`uoh-mh01`)
**Role:** `thief`
**Companion repository (police agent): https://github.com/mohamadhassarma/uoh-mh01-police**

> Both repositories of this group must be cross-linked. This is the thief repo;
> the link above points at the police repo, and that repo links back here.

---

## 1. Formal model ג€” Dec-POMDP

> **TODO (required):** scientific description of the formalism used to model the race ג€”
> state space, observations, and the uncertainty structure. See Ch. 1 of the rulebook.

## 2. FastMCP orchestration dilemmas

> **TODO (required):** discussion of the development trade-offs around inter-agent
> communication: turn management, network-failure handling, the roles of the
> Orchestrator and the Gatekeeper. See Ch. 2 and Ch. 8.

## 3. Strategies implemented

> **TODO (required):** the decision-making mechanism chosen, belief map, pheromone
> trails, and how the move is selected. See Ch. 4 and Ch. 6.

## 4. Reinforcement-learning curves / experiments

> **TODO (required):** figures, tables, curves. Attach GUI belief-map screenshot and
> a Replay screenshot showing `Verified OK`.

## 5. Results and reflection

> **TODO (required):** league results, what worked, what did not.

---

## Repository contents (mandatory checklist)

- [x] `README.md` ג€” this academic report
- [x] `config/` ג€” `game.json` (signed shared contract) + `thief/game.toml` (private)
- [x] `prd/` ג€” one PRD per development stage
- [x] `PLAN.md` ג€” development plan
- [x] `TODO.md` ג€” task list
- [ ] Annotated git tag `v1.0-submission` pushed
- [ ] GUI belief-map screenshot attached
- [ ] Replay screenshot with `Verified OK` attached
- [ ] No secrets committed (`credentials.json`, `token.json` are gitignored)

## Running

```powershell
uv sync
uv run python -m police_thief peer --role thief
```

Replay a saved match:

```powershell
uv run python -m police_thief replay --log logs/thief_match.json
```

## Process separation

The police and thief agents **must** run as two fully separate processes under
separate configuration directories. This repository contains the `thief` side only.
No shared memory, no shared variables, no shared live module between the two roles.