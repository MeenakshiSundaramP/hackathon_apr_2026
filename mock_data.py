"""Mock data provider — loads from JSON files when Neo4j is unavailable."""

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR = Path(os.path.dirname(__file__)) / "data"


def _load_json(name):
    with open(DATA_DIR / name) as f:
        return json.load(f)


def _build_dataframes():
    workforce = _load_json("workforce.json")
    org = _load_json("org-chart.json")
    tickets = _load_json("tickets.json")

    employees = pd.DataFrame(workforce)
    tickets_df = pd.DataFrame(tickets)

    # Build team membership from org-chart
    team_members = []
    team_leads = {}
    for t in org["teams"]:
        team_leads[t["team"]] = t["team_lead"]
        for m in t["members"]:
            team_members.append({"employee_id": m, "team": t["team"]})
    membership = pd.DataFrame(team_members)

    emp = employees.merge(membership, on="employee_id")

    # Build allocations flat table
    alloc_rows = []
    for w in workforce:
        for a in w.get("allocations", []):
            alloc_rows.append({
                "employee_id": w["employee_id"],
                "name": w["name"],
                "role": w["role"],
                "project": a["project"],
                "percentage": a["percentage"],
            })
    allocations = pd.DataFrame(alloc_rows)

    # Build skills flat table
    skill_rows = []
    for w in workforce:
        for s in w.get("skills", []):
            skill_rows.append({"employee_id": w["employee_id"], "name": w["name"], "skill": s})
    skills = pd.DataFrame(skill_rows)

    # Build reporting relationships
    report_rows = []
    for w in workforce:
        if w.get("team_lead"):
            lead = next((e for e in workforce if e["employee_id"] == w["team_lead"]), None)
            if lead:
                report_rows.append({
                    "employee_id": w["employee_id"],
                    "name": w["name"],
                    "manager_id": lead["employee_id"],
                    "manager": lead["name"],
                    "manager_role": lead["role"],
                })
    # Team leads report to director
    director = next((e for e in workforce if e["employee_id"] == org["director"]), None)
    if director:
        for t in org["teams"]:
            lead_id = t["team_lead"]
            if lead_id and lead_id != org["director"]:
                lead = next((e for e in workforce if e["employee_id"] == lead_id), None)
                if lead:
                    report_rows.append({
                        "employee_id": lead["employee_id"],
                        "name": lead["name"],
                        "manager_id": director["employee_id"],
                        "manager": director["name"],
                        "manager_role": director["role"],
                    })
    reports = pd.DataFrame(report_rows)

    return emp, tickets_df, allocations, skills, reports


_emp, _tickets, _allocations, _skills, _reports = _build_dataframes()


def _filter(df, teams, team_col="team"):
    return df[df[team_col].isin(teams)].copy()


def _tenure_band(start_str):
    d = date.fromisoformat(start_str)
    months = (date.today().year - d.year) * 12 + (date.today().month - d.month)
    years = months // 12
    if months < 12:
        band = "New (<1yr)"
    elif months < 24:
        band = "Developing (1-2yr)"
    elif months < 48:
        band = "Established (2-4yr)"
    else:
        band = "Long-serving (4yr+)"
    return years, band


# ---- Public query functions ----

def get_teams():
    return pd.DataFrame({"team": sorted(_emp["team"].unique())})


def get_headcount(teams):
    return pd.DataFrame({"headcount": [len(_filter(_emp, teams))]})


def get_open_ticket_count(teams):
    t = _filter(_tickets, teams, "assigned_team")
    return pd.DataFrame({"open_tickets": [len(t[t["status"] == "open"])]})


def get_overloaded_count(teams):
    e = _filter(_emp, teams)
    return pd.DataFrame({"overloaded": [len(e[e["total_allocation"] > 100])]})


def get_avg_allocation(teams):
    e = _filter(_emp, teams)
    return pd.DataFrame({"avg_allocation": [round(e["total_allocation"].mean())]})


def get_hierarchy(teams):
    r = _reports[_reports["employee_id"].isin(_filter(_emp, teams)["employee_id"])]
    if r.empty:
        return pd.DataFrame()
    grouped = r.groupby(["manager", "manager_role"]).agg(
        direct_reports=("name", list),
        report_count=("name", "count"),
    ).reset_index().rename(columns={"manager_role": "role"})
    return grouped.sort_values("report_count", ascending=False)


def get_tenure(teams):
    e = _filter(_emp, teams)
    rows = []
    for _, r in e.iterrows():
        years, band = _tenure_band(r["start_date"])
        rows.append({
            "name": r["name"], "role": r["role"], "team": r["team"],
            "start_date": r["start_date"], "years_service": years, "tenure_band": band,
        })
    return pd.DataFrame(rows).sort_values("years_service", ascending=False)


def get_location(teams):
    e = _filter(_emp, teams)
    return e.groupby("location").size().reset_index(name="headcount").sort_values("headcount", ascending=False)


def get_capacity(teams):
    e = _filter(_emp, teams)
    return e.groupby("team").agg(
        headcount=("employee_id", "count"),
        avg_allocation=("total_allocation", lambda x: round(x.mean())),
        min_allocation=("total_allocation", "min"),
        max_allocation=("total_allocation", "max"),
        overloaded=("total_allocation", lambda x: (x > 100).sum()),
    ).reset_index().sort_values("avg_allocation", ascending=False)


def get_overloaded(teams):
    e = _filter(_emp, teams)
    e = e[e["total_allocation"] > 100][["name", "role", "team", "total_allocation"]]
    return e.rename(columns={"total_allocation": "allocation"}).sort_values("allocation", ascending=False)


def get_underutilised(teams):
    e = _filter(_emp, teams)
    e = e[e["total_allocation"] < 80][["name", "role", "team", "total_allocation"]].copy()
    e["spare_capacity"] = 100 - e["total_allocation"]
    return e.rename(columns={"total_allocation": "allocation"}).sort_values("spare_capacity", ascending=False)


def get_workload(teams):
    e = _filter(_emp, teams)
    a = _allocations[_allocations["employee_id"].isin(e["employee_id"])]
    merged = a.merge(e[["employee_id", "team"]], on="employee_id")
    return merged[["name", "team", "project", "percentage"]].rename(columns={"percentage": "pct"}).sort_values(["name", "pct"], ascending=[True, False])


def get_open_tickets(teams):
    t = _filter(_tickets, teams, "assigned_team")
    t = t[t["status"] == "open"][["ticket_id", "assigned_team", "category", "priority", "created_date", "description"]]
    t = t.rename(columns={"ticket_id": "ticket", "assigned_team": "team", "created_date": "created"})
    priority_order = {"high": 1, "medium": 2, "low": 3}
    t["_sort"] = t["priority"].map(priority_order)
    return t.sort_values(["_sort", "created"]).drop(columns="_sort")


def get_ticket_volume(teams):
    t = _filter(_tickets, teams, "assigned_team")
    grouped = t.groupby("assigned_team").agg(
        total=("ticket_id", "count"),
        open=("status", lambda x: (x == "open").sum()),
        resolved=("status", lambda x: (x == "resolved").sum()),
    ).reset_index().rename(columns={"assigned_team": "team"})
    return grouped.sort_values("total", ascending=False)


def get_ticket_categories(teams):
    t = _filter(_tickets, teams, "assigned_team")
    grouped = t.groupby("category").agg(
        total=("ticket_id", "count"),
        open=("status", lambda x: (x == "open").sum()),
    ).reset_index()
    return grouped.sort_values("total", ascending=False)


def get_resolution_time(teams):
    t = _filter(_tickets, teams, "assigned_team")
    t = t[(t["status"] == "resolved") & (t["resolved_date"].notna())].copy()
    t["days"] = (pd.to_datetime(t["resolved_date"]) - pd.to_datetime(t["created_date"])).dt.days
    grouped = t.groupby(["assigned_team", "category"]).agg(
        avg_days=("days", lambda x: round(x.mean(), 1)),
        min_days=("days", "min"),
        max_days=("days", "max"),
        tickets=("ticket_id", "count"),
    ).reset_index().rename(columns={"assigned_team": "team"})
    return grouped.sort_values("avg_days", ascending=False)


def get_backlog_trend(teams):
    t = _filter(_tickets, teams, "assigned_team")
    created = t[["created_date"]].rename(columns={"created_date": "date"}).assign(event="created")
    resolved = t[t["resolved_date"].notna()][["resolved_date"]].rename(columns={"resolved_date": "date"}).assign(event="resolved")
    trend = pd.concat([created, resolved], ignore_index=True)
    trend["date"] = pd.to_datetime(trend["date"])
    trend["delta"] = trend["event"].map({"created": 1, "resolved": -1})
    trend = trend.sort_values("date")
    trend["open_backlog"] = trend["delta"].cumsum()
    return trend.groupby("date").last().reset_index()[["date", "open_backlog"]]


def get_tickets_per_person(teams):
    t = _filter(_tickets, teams, "assigned_team")
    e = _filter(_emp, teams)
    tvol = t.groupby("assigned_team").size().reset_index(name="total_tickets").rename(columns={"assigned_team": "team"})
    hc = e.groupby("team").size().reset_index(name="headcount")
    merged = tvol.merge(hc, on="team")
    merged["tickets_per_person"] = round(merged["total_tickets"] / merged["headcount"], 1)
    return merged.sort_values("tickets_per_person", ascending=False)


def get_spof(teams):
    e = _filter(_emp, teams)
    s = _skills[_skills["employee_id"].isin(e["employee_id"])]
    counts = s.groupby("skill").agg(holders=("name", list), count=("name", "count")).reset_index()
    spof = counts[counts["count"] == 1].copy()
    spof["sole_holder"] = spof["holders"].str[0]
    return spof[["skill", "sole_holder"]].sort_values("skill")


def get_all_skills(teams):
    e = _filter(_emp, teams)
    s = _skills[_skills["employee_id"].isin(e["employee_id"])]
    return pd.DataFrame({"skill": sorted(s["skill"].unique())})


def get_skill_holders(skill, teams):
    e = _filter(_emp, teams)
    s = _skills[(_skills["skill"] == skill) & (_skills["employee_id"].isin(e["employee_id"]))]
    merged = s.merge(e[["employee_id", "role", "team", "total_allocation"]], on="employee_id")
    return merged[["name", "role", "team", "total_allocation"]].rename(
        columns={"total_allocation": "allocation"}
    ).sort_values("allocation")


def get_grade_distribution(teams):
    e = _filter(_emp, teams)
    return e.groupby(["team", "grade"]).size().reset_index(name="count").sort_values(["team", "grade"])


def get_project_effort(teams):
    e = _filter(_emp, teams)
    a = _allocations[_allocations["employee_id"].isin(e["employee_id"])]
    grouped = a.groupby("project").agg(
        people=("employee_id", "nunique"),
        total_effort=("percentage", "sum"),
    ).reset_index()
    return grouped.sort_values("total_effort", ascending=False)


def get_cross_team(teams):
    e = _filter(_emp, teams)
    a = _allocations[_allocations["employee_id"].isin(e["employee_id"])]
    merged = a.merge(e[["employee_id", "team"]], on="employee_id")
    grouped = merged.groupby("project").agg(
        teams=("team", lambda x: list(set(x))),
        team_count=("team", "nunique"),
    ).reset_index()
    return grouped[grouped["team_count"] > 1].sort_values("team_count", ascending=False)


def get_project_detail(project, teams):
    e = _filter(_emp, teams)
    a = _allocations[(_allocations["project"] == project) & (_allocations["employee_id"].isin(e["employee_id"]))]
    merged = a.merge(e[["employee_id", "team"]], on="employee_id")
    return merged[["name", "role", "team", "percentage"]].rename(
        columns={"percentage": "allocation"}
    ).sort_values("allocation", ascending=False)
