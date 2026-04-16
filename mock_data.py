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
    costs = _load_json("workforce-cost.json")

    # Build role+grade -> cost lookup
    cost_map = {}
    for rc in costs["role_costs"]:
        cost_map[(rc["role"], rc["grade"])] = rc
    for w in workforce:
        key = (w["role"], w["grade"])
        if key in cost_map:
            c = cost_map[key]
            w["annual_salary"] = c["annual_salary"]
            w["day_rate"] = c["day_rate"]
            w["on_costs_pct"] = c["on_costs_pct"]
            w["full_cost"] = int(c["annual_salary"] * (1 + c["on_costs_pct"] / 100.0))
        else:
            w["annual_salary"] = 0
            w["day_rate"] = 0
            w["on_costs_pct"] = 0
            w["full_cost"] = 0

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

    emp = employees.merge(membership, on="employee_id", suffixes=('_orig', ''))
    if 'team_orig' in emp.columns:
        emp = emp.drop(columns=['team_orig'])

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


# ---- Ticket analysis functions ----

def get_slow_open_combinations(teams):
    t = _filter(_tickets, teams, "assigned_team")
    resolved = t[(t["status"] == "resolved") & (t["resolved_date"].notna())].copy()
    resolved["days"] = (pd.to_datetime(resolved["resolved_date"]) - pd.to_datetime(resolved["created_date"])).dt.days
    rows = []
    for (team, cat), grp in t.groupby(["assigned_team", "category"]):
        res_grp = resolved[(resolved["assigned_team"] == team) & (resolved["category"] == cat)]
        if len(res_grp) == 0:
            continue
        open_grp = t[(t["assigned_team"] == team) & (t["category"] == cat) & (t["status"] == "open")]
        rows.append({
            "team": team, "category": cat,
            "total_tickets": len(grp),
            "still_open": len(open_grp),
            "open_high": int((open_grp["priority"] == "high").sum()),
            "resolved": len(res_grp),
            "avg_days": round(res_grp["days"].mean(), 1),
        })
    return pd.DataFrame(rows).sort_values("avg_days", ascending=False) if rows else pd.DataFrame()


def get_redeployment_data(teams):
    e = _filter(_emp, teams)
    t = _filter(_tickets, teams, "assigned_team")
    rows = []
    for team in teams:
        team_emp = e[e["team"] == team]
        headcount = len(team_emp)
        if headcount == 0:
            continue
        avg_alloc = round(team_emp["total_allocation"].mean())
        spare = team_emp[team_emp["total_allocation"] < 80]
        spare_names = spare["name"].tolist()
        open_tickets = int((t[(t["assigned_team"] == team) & (t["status"] == "open")].shape[0]))
        rows.append({
            "team": team, "headcount": headcount, "avg_alloc": avg_alloc,
            "spare_staff": len(spare_names), "spare_names": spare_names,
            "open_tickets": open_tickets,
        })
    return pd.DataFrame(rows).sort_values("open_tickets", ascending=False)


def get_pressure_view(teams):
    e = _filter(_emp, teams)
    t = _filter(_tickets, teams, "assigned_team")
    rows = []
    for team in teams:
        team_emp = e[e["team"] == team]
        headcount = len(team_emp)
        if headcount == 0:
            continue
        avg_alloc = round(team_emp["total_allocation"].mean())
        overloaded = int((team_emp["total_allocation"] > 100).sum())
        team_tickets = t[t["assigned_team"] == team]
        total_tickets = len(team_tickets)
        open_tickets = int((team_tickets["status"] == "open").sum())
        tpp = round(total_tickets / headcount, 1) if total_tickets > 0 else 0.0
        if avg_alloc > 100 and open_tickets > 0:
            status = "CRITICAL"
        elif avg_alloc >= 90 and open_tickets > 0:
            status = "AT RISK"
        elif avg_alloc > 100:
            status = "OVER-COMMITTED"
        else:
            status = "OK"
        rows.append({
            "team": team, "headcount": headcount, "avg_allocation": avg_alloc,
            "overloaded_staff": overloaded, "total_tickets": total_tickets,
            "open_tickets": open_tickets, "tickets_per_person": tpp,
            "pressure_status": status,
        })
    return pd.DataFrame(rows).sort_values("avg_allocation", ascending=False)


def get_project_fragmentation(teams):
    e = _filter(_emp, teams)
    a = _allocations[_allocations["employee_id"].isin(e["employee_id"])]
    merged = a.merge(e[["employee_id", "role", "team", "total_allocation"]], on="employee_id", suffixes=('_alloc', ''))
    if 'role_alloc' in merged.columns:
        merged = merged.drop(columns=['role_alloc'])
    grouped = merged.groupby(["name", "role", "team", "total_allocation"]).agg(
        project_count=("project", "count"),
        avg_slice=("percentage", lambda x: round(x.mean())),
        projects=("project", lambda x: [f"{p} ({pct}%)" for p, pct in zip(x, merged.loc[x.index, "percentage"])]),
    ).reset_index().rename(columns={"total_allocation": "allocation"})
    result = grouped[grouped["project_count"] >= 3].sort_values(
        ["project_count", "allocation"], ascending=[False, False]
    )
    return result


def get_team_fragility(teams):
    e = _filter(_emp, teams)
    s = _skills[_skills["employee_id"].isin(e["employee_id"])]
    rows = []
    for team in teams:
        team_emp = e[e["team"] == team]
        headcount = len(team_emp)
        if headcount == 0:
            continue
        absence_impact_pct = round(100.0 / headcount)
        team_skills = s[s["employee_id"].isin(team_emp["employee_id"])]
        skill_counts = team_skills.groupby("skill")["employee_id"].nunique()
        unique_skills = int((skill_counts == 1).sum())
        fragility_score = round(absence_impact_pct * 0.4 + unique_skills * 0.6)
        rows.append({
            "team": team, "headcount": headcount,
            "absence_impact_pct": absence_impact_pct,
            "unique_skills": unique_skills,
            "fragility_score": fragility_score,
        })
    return pd.DataFrame(rows).sort_values("fragility_score", ascending=False)


def get_departure_impact(teams):
    e = _filter(_emp, teams)
    s = _skills[_skills["employee_id"].isin(e["employee_id"])]
    all_skill_counts = s.groupby("skill")["employee_id"].nunique()
    unique_skills_set = set(all_skill_counts[all_skill_counts == 1].index)
    rows = []
    for _, emp in e.iterrows():
        emp_skills = s[s["employee_id"] == emp["employee_id"]]["skill"].tolist()
        at_risk = [sk for sk in emp_skills if sk in unique_skills_set]
        if at_risk:
            rows.append({
                "name": emp["name"], "role": emp["role"], "team": emp["team"],
                "allocation": emp["total_allocation"],
                "unique_skills_lost": len(at_risk),
                "skills_at_risk": at_risk,
            })
    return pd.DataFrame(rows).sort_values("unique_skills_lost", ascending=False) if rows else pd.DataFrame()


def get_ageing_tickets(teams):
    t = _filter(_tickets, teams, "assigned_team")
    t = t[t["status"] == "open"].copy()
    t["days_open"] = (pd.Timestamp.today() - pd.to_datetime(t["created_date"])).dt.days
    t["age_band"] = t["days_open"].apply(
        lambda d: "Critical (>21d)" if d > 21 else "Warning (>14d)" if d > 14 else "Monitor (>7d)" if d > 7 else "Recent (<7d)"
    )
    return t[["ticket_id", "assigned_team", "category", "priority", "created_date", "days_open", "age_band", "description"]].rename(
        columns={"ticket_id": "ticket", "assigned_team": "team", "created_date": "created"}
    ).sort_values("days_open", ascending=False)


def get_resolution_by_priority(teams):
    t = _filter(_tickets, teams, "assigned_team")
    t = t[(t["status"] == "resolved") & (t["resolved_date"].notna())].copy()
    t["days"] = (pd.to_datetime(t["resolved_date"]) - pd.to_datetime(t["created_date"])).dt.days
    grouped = t.groupby("priority").agg(
        tickets=("ticket_id", "count"),
        avg_days=("days", lambda x: round(x.mean(), 1)),
        min_days=("days", "min"),
        max_days=("days", "max"),
    ).reset_index()
    order = {"high": 0, "medium": 1, "low": 2}
    return grouped.sort_values("priority", key=lambda x: x.map(order))


def get_resolution_variance(teams):
    t = _filter(_tickets, teams, "assigned_team")
    t = t[(t["status"] == "resolved") & (t["resolved_date"].notna())].copy()
    t["days"] = (pd.to_datetime(t["resolved_date"]) - pd.to_datetime(t["created_date"])).dt.days
    grouped = t.groupby("category").agg(
        tickets=("ticket_id", "count"),
        avg_days=("days", lambda x: round(x.mean(), 1)),
        min_days=("days", "min"),
        max_days=("days", "max"),
        range_days=("days", lambda x: x.max() - x.min()),
        stddev_days=("days", lambda x: round(x.std(), 1) if len(x) > 1 else 0.0),
    ).reset_index()
    return grouped.sort_values("stddev_days", ascending=False)


# ---- Cost functions ----

def get_total_cost(teams):
    e = _filter(_emp, teams)
    return pd.DataFrame({"total_cost": [e["full_cost"].sum()]})


def get_cost_summary(teams):
    e = _filter(_emp, teams)
    return pd.DataFrame({
        "total_cost": [e["full_cost"].sum()],
        "total_salary": [e["annual_salary"].sum()],
        "avg_cost": [round(e["full_cost"].mean())],
        "total_on_costs": [e["full_cost"].sum() - e["annual_salary"].sum()],
    })


def get_team_costs(teams):
    e = _filter(_emp, teams)
    return e.groupby("team").agg(
        headcount=("employee_id", "count"),
        total_salary=("annual_salary", "sum"),
        total_cost=("full_cost", "sum"),
        avg_cost_per_head=("full_cost", lambda x: round(x.mean())),
    ).reset_index().sort_values("total_cost", ascending=False)


def get_project_costs(teams):
    e = _filter(_emp, teams)
    a = _allocations[_allocations["employee_id"].isin(e["employee_id"])]
    merged = a.merge(e[["employee_id", "full_cost"]], on="employee_id")
    merged["allocated_cost"] = (merged["full_cost"] * merged["percentage"] / 100).astype(int)
    grouped = merged.groupby("project").agg(
        people=("employee_id", "nunique"),
        allocated_cost=("allocated_cost", "sum"),
    ).reset_index()
    return grouped.sort_values("allocated_cost", ascending=False)


def get_cost_per_ticket(teams):
    e = _filter(_emp, teams)
    t = _filter(_tickets, teams, "assigned_team")
    team_cost = e.groupby("team")["full_cost"].sum().reset_index(name="team_cost")
    ticket_count = t.groupby("assigned_team").size().reset_index(name="tickets").rename(columns={"assigned_team": "team"})
    merged = team_cost.merge(ticket_count, on="team")
    merged["cost_per_ticket"] = (merged["team_cost"] / merged["tickets"]).astype(int)
    return merged.sort_values("cost_per_ticket", ascending=False)


def get_cost_roster(teams):
    e = _filter(_emp, teams)
    return e[["name", "role", "grade", "team", "annual_salary", "full_cost", "day_rate", "total_allocation"]].rename(
        columns={"annual_salary": "salary", "total_allocation": "allocation"}
    ).sort_values("full_cost", ascending=False)


def get_overallocation_cost(teams):
    e = _filter(_emp, teams)
    over = e[e["total_allocation"] > 100].copy()
    over["excess_cost"] = ((over["full_cost"] * (over["total_allocation"] - 100)) / 100).astype(int)
    return over[["name", "role", "team", "total_allocation", "full_cost", "excess_cost"]].rename(
        columns={"total_allocation": "allocation"}
    ).sort_values("excess_cost", ascending=False)


def get_automation_candidates(teams):
    e = _filter(_emp, teams)
    t = _filter(_tickets, teams, "assigned_team")
    resolved = t[(t["status"] == "resolved") & (t["resolved_date"].notna())].copy()
    resolved["days"] = (pd.to_datetime(resolved["resolved_date"]) - pd.to_datetime(resolved["created_date"])).dt.days
    rows = []
    for (cat, team), grp in resolved.groupby(["category", "assigned_team"]):
        volume = len(grp)
        avg_days = round(grp["days"].mean(), 1)
        stddev = round(grp["days"].std(), 1) if len(grp) > 1 else 0.0
        min_days = int(grp["days"].min())
        max_days = int(grp["days"].max())
        low_pct = round(100.0 * (grp["priority"] == "low").sum() / len(grp))
        team_emp = e[e["team"] == team]
        avg_day_rate = round(team_emp["day_rate"].mean()) if len(team_emp) > 0 else 0
        annual_cost = int(volume * avg_days * avg_day_rate * 0.25)
        if stddev <= 1.0 and low_pct >= 80:
            fit = "HIGH"
            saving = int(annual_cost * 0.8)
        elif stddev <= 5.0 and low_pct >= 50:
            fit = "MEDIUM"
            saving = int(annual_cost * 0.4)
        else:
            fit = "LOW"
            saving = int(annual_cost * 0.1)
        rows.append({
            "category": cat, "team": team, "volume": volume,
            "avg_days": avg_days, "stddev": stddev,
            "min_days": min_days, "max_days": max_days,
            "low_priority_pct": low_pct, "annual_cost": annual_cost,
            "potential_saving": saving, "automation_fit": fit,
        })
    df = pd.DataFrame(rows)
    fit_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return df.sort_values(["automation_fit", "annual_cost"], key=lambda x: x.map(fit_order) if x.name == "automation_fit" else -x, ascending=True)
