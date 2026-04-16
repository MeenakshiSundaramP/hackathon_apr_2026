"""Utilisation analysis module — provides deep workforce utilisation insights."""

import json
import os
from pathlib import Path
from datetime import date

import pandas as pd

DATA_DIR = Path(os.path.dirname(__file__)) / "data"


def _load():
    with open(DATA_DIR / "workforce.json") as f:
        workforce = json.load(f)
    with open(DATA_DIR / "workforce-cost.json") as f:
        costs = json.load(f)
    with open(DATA_DIR / "org-chart.json") as f:
        org = json.load(f)
    with open(DATA_DIR / "tickets.json") as f:
        tickets = json.load(f)

    cost_map = {}
    for rc in costs["role_costs"]:
        cost_map[(rc["role"], rc["grade"])] = rc
    for w in workforce:
        c = cost_map.get((w["role"], w["grade"]), {})
        w["annual_salary"] = c.get("annual_salary", 0)
        w["day_rate"] = c.get("day_rate", 0)
        w["full_cost"] = int(c.get("annual_salary", 0) * (1 + c.get("on_costs_pct", 0) / 100.0))

    # Build team membership
    team_map = {}
    for t in org["teams"]:
        for m in t["members"]:
            team_map[m] = t["team"]
    for w in workforce:
        w["team_from_org"] = team_map.get(w["employee_id"], w.get("team", "Unknown"))

    return workforce, tickets


_workforce, _tickets = _load()


def utilisation_summary():
    """Overall utilisation stats across the directorate."""
    allocs = [w["total_allocation"] for w in _workforce]
    return {
        "headcount": len(_workforce),
        "avg_utilisation": round(sum(allocs) / len(allocs), 1),
        "fully_utilised": sum(1 for a in allocs if 90 <= a <= 100),
        "overloaded": sum(1 for a in allocs if a > 100),
        "underutilised": sum(1 for a in allocs if a < 80),
        "idle_capacity_pct": round(sum(max(0, 100 - a) for a in allocs) / len(allocs), 1),
        "excess_pct": round(sum(max(0, a - 100) for a in allocs) / len(allocs), 1),
        "total_cost": sum(w["full_cost"] for w in _workforce),
        "wasted_cost": sum(int(w["full_cost"] * max(0, 100 - w["total_allocation"]) / 100) for w in _workforce),
        "excess_cost": sum(int(w["full_cost"] * max(0, w["total_allocation"] - 100) / 100) for w in _workforce),
    }


def utilisation_by_team():
    """Utilisation breakdown per team."""
    teams = {}
    for w in _workforce:
        t = w["team_from_org"]
        if t not in teams:
            teams[t] = {"team": t, "headcount": 0, "allocs": [], "cost": 0}
        teams[t]["headcount"] += 1
        teams[t]["allocs"].append(w["total_allocation"])
        teams[t]["cost"] += w["full_cost"]

    rows = []
    for t, d in teams.items():
        allocs = d["allocs"]
        rows.append({
            "team": t,
            "headcount": d["headcount"],
            "avg_utilisation": round(sum(allocs) / len(allocs), 1),
            "min_utilisation": min(allocs),
            "max_utilisation": max(allocs),
            "overloaded": sum(1 for a in allocs if a > 100),
            "underutilised": sum(1 for a in allocs if a < 80),
            "team_cost": d["cost"],
            "idle_cost": sum(int(d["cost"] / len(allocs) * max(0, 100 - a) / 100) for a in allocs),
            "utilisation_band": "Over" if sum(allocs) / len(allocs) > 100 else "Optimal" if sum(allocs) / len(allocs) >= 85 else "Under",
        })
    return pd.DataFrame(rows).sort_values("avg_utilisation", ascending=False)


def utilisation_by_person():
    """Per-person utilisation with status classification."""
    rows = []
    for w in _workforce:
        a = w["total_allocation"]
        projects = [f"{p['project']} ({p['percentage']}%)" for p in w.get("allocations", [])]
        if a > 100:
            status = "🔴 Overloaded"
            risk = "Burnout / quality risk"
        elif a >= 85:
            status = "🟢 Optimal"
            risk = "None"
        elif a >= 50:
            status = "🟡 Underutilised"
            risk = "Capacity waste"
        else:
            status = "🔵 Significantly under"
            risk = "Redeployment candidate"
        rows.append({
            "name": w["name"],
            "role": w["role"],
            "team": w["team_from_org"],
            "grade": w["grade"],
            "allocation": a,
            "project_count": len(w.get("allocations", [])),
            "projects": projects,
            "status": status,
            "risk": risk,
            "full_cost": w["full_cost"],
            "effective_cost": int(w["full_cost"] * min(a, 100) / 100),
            "wasted_cost": int(w["full_cost"] * max(0, 100 - a) / 100),
        })
    return pd.DataFrame(rows).sort_values("allocation", ascending=False)


def utilisation_by_grade():
    """Utilisation patterns by grade — are senior staff more overloaded?"""
    grades = {}
    for w in _workforce:
        g = w["grade"]
        if g not in grades:
            grades[g] = {"allocs": [], "costs": []}
        grades[g]["allocs"].append(w["total_allocation"])
        grades[g]["costs"].append(w["full_cost"])

    grade_order = {"AO": 1, "EO": 2, "HEO": 3, "SEO": 4, "G7": 5, "G6": 6}
    rows = []
    for g, d in grades.items():
        allocs = d["allocs"]
        rows.append({
            "grade": g,
            "count": len(allocs),
            "avg_utilisation": round(sum(allocs) / len(allocs), 1),
            "overloaded": sum(1 for a in allocs if a > 100),
            "underutilised": sum(1 for a in allocs if a < 80),
            "avg_cost": round(sum(d["costs"]) / len(d["costs"])),
        })
    return pd.DataFrame(rows).sort_values("grade", key=lambda x: x.map(grade_order))


def utilisation_efficiency():
    """Cost efficiency — what percentage of spend is productive vs wasted."""
    total_cost = sum(w["full_cost"] for w in _workforce)
    productive = sum(int(w["full_cost"] * min(w["total_allocation"], 100) / 100) for w in _workforce)
    idle = sum(int(w["full_cost"] * max(0, 100 - w["total_allocation"]) / 100) for w in _workforce)
    excess = sum(int(w["full_cost"] * max(0, w["total_allocation"] - 100) / 100) for w in _workforce)
    return pd.DataFrame([{
        "category": "Productive work",
        "amount": productive,
        "pct": round(100 * productive / total_cost, 1),
    }, {
        "category": "Idle capacity (under-allocation)",
        "amount": idle,
        "pct": round(100 * idle / total_cost, 1),
    }, {
        "category": "Excess (over-allocation / overtime)",
        "amount": excess,
        "pct": round(100 * excess / total_cost, 1),
    }])


def rebalancing_opportunities():
    """Identify specific rebalancing moves — who can give capacity to whom."""
    under = [(w["name"], w["role"], w["team_from_org"], w["total_allocation"], w["skills"])
             for w in _workforce if w["total_allocation"] < 80]
    over_teams = set()
    for w in _workforce:
        if w["total_allocation"] > 100:
            over_teams.add(w["team_from_org"])

    rows = []
    for name, role, team, alloc, skills in under:
        spare = 100 - alloc
        for ot in over_teams:
            if ot != team:
                rows.append({
                    "available_person": name,
                    "current_team": team,
                    "current_allocation": alloc,
                    "spare_capacity": spare,
                    "target_team": ot,
                    "skills": ", ".join(skills[:3]),
                    "recommendation": f"Redeploy {spare}% of {name}'s time to {ot}",
                })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def project_utilisation():
    """How efficiently is each project using its allocated people."""
    projects = {}
    for w in _workforce:
        for a in w.get("allocations", []):
            p = a["project"]
            if p not in projects:
                projects[p] = {"people": [], "total_pct": 0, "total_cost": 0}
            projects[p]["people"].append(w["name"])
            projects[p]["total_pct"] += a["percentage"]
            projects[p]["total_cost"] += int(w["full_cost"] * a["percentage"] / 100)

    rows = []
    for p, d in projects.items():
        people_count = len(set(d["people"]))
        avg_per_person = round(d["total_pct"] / people_count, 0) if people_count else 0
        rows.append({
            "project": p,
            "people": people_count,
            "total_allocation": d["total_pct"],
            "avg_per_person": avg_per_person,
            "allocated_cost": d["total_cost"],
            "fragmented": "Yes" if avg_per_person < 40 and people_count > 1 else "No",
        })
    return pd.DataFrame(rows).sort_values("allocated_cost", ascending=False)
