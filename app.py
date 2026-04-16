import os
import streamlit as st
import pandas as pd
import altair as alt
from dotenv import load_dotenv

load_dotenv()

# --- Data source detection ---
USE_NEO4J = False
try:
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    pwd = os.getenv("NEO4J_PASSWORD")
    if uri and user and pwd:
        _driver = GraphDatabase.driver(uri, auth=(user, pwd))
        _driver.verify_connectivity()
        USE_NEO4J = True
except Exception:
    pass

if not USE_NEO4J:
    import mock_data


def run_query(query, params=None):
    with _driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        result = session.run(query, params or {})
        return pd.DataFrame([r.data() for r in result])


# --- Page config ---
st.set_page_config(page_title="Workforce Visibility Dashboard", layout="wide", page_icon="🏛️")
st.title("🏛️ Workforce & Operational Visibility")
if USE_NEO4J:
    st.caption("Directorate of Corporate Services — Live from Neo4j")
else:
    st.caption("Directorate of Corporate Services — Running on mock data (Neo4j unavailable)")
    st.toast("⚠️ Neo4j not connected — using local JSON mock data", icon="📂")

# --- Load all teams (no sidebar filter) ---
if USE_NEO4J:
    teams_df = run_query("MATCH (t:Team) RETURN t.name AS team ORDER BY t.name")
else:
    teams_df = mock_data.get_teams()
team_filter = teams_df["team"].tolist()

# --- Pre-compute automation data (needed by both Overview and Automation tabs) ---
if USE_NEO4J:
    auto_df = run_query("""
        MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
        WHERE tk.status = 'resolved' AND tk.resolved_date IS NOT NULL
        WITH tk.category AS category, t.name AS team,
             duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days,
             tk.priority AS priority
        WITH category, team,
             count(*) AS volume,
             round(avg(days), 1) AS avg_days,
             round(stDev(days), 1) AS stddev,
             min(days) AS min_days,
             max(days) AS max_days,
             size(collect(CASE WHEN priority = 'low' THEN 1 END)) AS low_pct_raw,
             size(collect(priority)) AS total_raw
        WITH category, team, volume, avg_days, stddev, min_days, max_days,
             round(100.0 * low_pct_raw / total_raw, 0) AS low_priority_pct
        MATCH (e:Employee)-[:MEMBER_OF]->(t2:Team {name: team})
        WITH category, team, volume, avg_days, stddev, min_days, max_days,
             low_priority_pct, round(avg(e.day_rate), 0) AS avg_day_rate
        WITH *,
             toInteger(volume * avg_days * avg_day_rate * 0.25) AS annual_cost,
             CASE
               WHEN stddev <= 1.0 AND low_priority_pct >= 80 THEN 'HIGH'
               WHEN stddev <= 5.0 AND low_priority_pct >= 50 THEN 'MEDIUM'
               ELSE 'LOW'
             END AS automation_fit
        RETURN category, team, volume, avg_days, stddev, min_days, max_days,
               low_priority_pct, annual_cost,
               CASE automation_fit
                 WHEN 'HIGH' THEN toInteger(annual_cost * 0.8)
                 WHEN 'MEDIUM' THEN toInteger(annual_cost * 0.4)
                 ELSE toInteger(annual_cost * 0.1)
               END AS potential_saving,
               automation_fit
        ORDER BY CASE automation_fit WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                 annual_cost DESC
    """, {"teams": team_filter})
else:
    auto_df = mock_data.get_automation_candidates(team_filter)

# --- Tab layout ---
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "📊 Overview", "👥 Capacity", "🎫 Tickets", "🧠 Skills & Risk", "📁 Projects", "💰 Cost & Budget", "🤖 Automation", "💬 Chat"
])

# ===================== TAB 1: OVERVIEW =====================
with tab1:
    col1, col2, col3, col4, col5m = st.columns(5)

    if USE_NEO4J:
        headcount_df = run_query("MATCH (e:Employee)-[:MEMBER_OF]->(t:Team) WHERE t.name IN $teams RETURN count(e) AS headcount", {"teams": team_filter})
        open_tickets_df = run_query("MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team) WHERE t.name IN $teams RETURN count(tk) AS open_tickets", {"teams": team_filter})
        overloaded_df = run_query("MATCH (e:Employee)-[:MEMBER_OF]->(t:Team) WHERE t.name IN $teams AND e.total_allocation > 100 RETURN count(e) AS overloaded", {"teams": team_filter})
        avg_alloc_df = run_query("MATCH (e:Employee)-[:MEMBER_OF]->(t:Team) WHERE t.name IN $teams RETURN round(avg(e.total_allocation), 0) AS avg_allocation", {"teams": team_filter})
        total_cost_df = run_query("MATCH (e:Employee)-[:MEMBER_OF]->(t:Team) WHERE t.name IN $teams RETURN sum(e.full_cost) AS total_cost", {"teams": team_filter})
    else:
        headcount_df = mock_data.get_headcount(team_filter)
        open_tickets_df = mock_data.get_open_ticket_count(team_filter)
        overloaded_df = mock_data.get_overloaded_count(team_filter)
        avg_alloc_df = mock_data.get_avg_allocation(team_filter)
        total_cost_df = mock_data.get_total_cost(team_filter)

    col1.metric("Headcount", int(headcount_df["headcount"].iloc[0]))
    col2.metric("Open Tickets", int(open_tickets_df["open_tickets"].iloc[0]))
    col3.metric("Overloaded Staff (>100%)", int(overloaded_df["overloaded"].iloc[0]))
    col4.metric("Avg Allocation", f"{int(avg_alloc_df['avg_allocation'].iloc[0])}%")
    col5m.metric("Total Annual Cost", f"£{int(total_cost_df['total_cost'].iloc[0]):,}")

    st.divider()

    # --- Combined Pressure View ---
    st.subheader("🔥 Combined Pressure View — Workforce × Operational Demand")
    st.caption("Which teams are simultaneously over-committed on project work AND handling high ticket volumes?")
    if USE_NEO4J:
        pressure_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team,
                 count(e) AS headcount,
                 round(avg(e.total_allocation), 0) AS avg_allocation,
                 sum(CASE WHEN e.total_allocation > 100 THEN 1 ELSE 0 END) AS overloaded_staff,
                 round(avg(e.full_cost), 0) AS avg_cost
            OPTIONAL MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t2:Team {name: team})
            WITH team, headcount, avg_allocation, overloaded_staff, avg_cost,
                 count(tk) AS total_tickets,
                 sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS open_tickets
            RETURN team, headcount, avg_allocation, overloaded_staff,
                   total_tickets, open_tickets,
                   CASE WHEN total_tickets > 0
                        THEN round(toFloat(total_tickets) / headcount, 1)
                        ELSE 0.0 END AS tickets_per_person,
                   CASE WHEN avg_allocation > 100 AND open_tickets > 0 THEN 'CRITICAL'
                        WHEN avg_allocation >= 90 AND open_tickets > 0 THEN 'AT RISK'
                        WHEN avg_allocation > 100 THEN 'OVER-COMMITTED'
                        ELSE 'OK' END AS pressure_status
            ORDER BY avg_allocation DESC
        """, {"teams": team_filter})
    else:
        pressure_df = mock_data.get_pressure_view(team_filter)
    if not pressure_df.empty:
        # Scatter plot: allocation vs ticket load
        scatter = alt.Chart(pressure_df).mark_circle(size=200).encode(
            x=alt.X("avg_allocation:Q", title="Avg Allocation %", scale=alt.Scale(domain=[60, 120])),
            y=alt.Y("tickets_per_person:Q", title="Tickets per Person"),
            color=alt.Color("pressure_status:N", title="Status",
                            scale=alt.Scale(
                                domain=["CRITICAL", "AT RISK", "OVER-COMMITTED", "OK"],
                                range=["#e74c3c", "#f39c12", "#e67e22", "#2ecc71"])),
            size=alt.Size("headcount:Q", title="Headcount", scale=alt.Scale(range=[100, 500])),
            tooltip=["team", "headcount", "avg_allocation", "overloaded_staff",
                     "total_tickets", "open_tickets", "tickets_per_person", "pressure_status"],
        ).properties(height=350)
        vline = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(color="orange", strokeDash=[5, 5]).encode(x="x:Q")
        text = alt.Chart(pressure_df).mark_text(dy=-15, fontSize=12, fontWeight="bold").encode(
            x=alt.X("avg_allocation:Q"),
            y=alt.Y("tickets_per_person:Q"),
            text="team:N",
        )
        st.altair_chart(scatter + vline + text, use_container_width=True)

        # Status summary
        def status_color(val):
            colors = {
                "CRITICAL": "background-color: #e74c3c; color: white",
                "AT RISK": "background-color: #fff3cd",
                "OVER-COMMITTED": "background-color: #ffeaa7",
                "OK": "background-color: #d4edda",
            }
            return colors.get(val, "")
        st.dataframe(
            pressure_df.style.map(status_color, subset=["pressure_status"]),
            use_container_width=True, hide_index=True,
        )

        critical = pressure_df[pressure_df["pressure_status"] == "CRITICAL"]
        if not critical.empty:
            teams_list = ", ".join(critical["team"].tolist())
            st.error(f"🚨 {teams_list} — over-committed on project work AND carrying open operational tickets. "
                     f"These teams need immediate attention: rebalance allocations, defer project work, or add capacity.")
        at_risk = pressure_df[pressure_df["pressure_status"] == "AT RISK"]
        if not at_risk.empty:
            teams_list = ", ".join(at_risk["team"].tolist())
            st.warning(f"⚠️ {teams_list} — near capacity with open tickets. Monitor closely.")

    st.divider()

    # --- Slowest team-category pairs with open flags ---
    st.subheader("⏳ Slowest Resolution × Open Backlog")
    st.caption("Team-category combinations with the longest avg resolution AND tickets still open — these need intervention.")
    if USE_NEO4J:
        slow_open_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, tk.category AS category,
                 count(tk) AS total_tickets,
                 sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS still_open,
                 sum(CASE WHEN tk.status = 'open' AND tk.priority = 'high' THEN 1 ELSE 0 END) AS open_high,
                 collect(CASE WHEN tk.status = 'resolved' AND tk.resolved_date IS NOT NULL
                              THEN duration.between(date(tk.created_date), date(tk.resolved_date)).days
                              ELSE NULL END) AS days_list
            WITH team, category, total_tickets, still_open, open_high,
                 [d IN days_list WHERE d IS NOT NULL] AS resolved_days
            WHERE size(resolved_days) > 0
            RETURN team, category, total_tickets, still_open, open_high,
                   size(resolved_days) AS resolved,
                   round(reduce(s = 0.0, d IN resolved_days | s + d) / size(resolved_days), 1) AS avg_days
            ORDER BY avg_days DESC
        """, {"teams": team_filter})
    else:
        slow_open_df = mock_data.get_slow_open_combinations(team_filter)
    if not slow_open_df.empty:
        def flag_row(row):
            if row["still_open"] > 0 and row["open_high"] > 0:
                return "🚨 Open high-priority"
            elif row["still_open"] > 0:
                return "⚠️ Open tickets"
            return "✅ Clear"
        slow_open_df["status"] = slow_open_df.apply(flag_row, axis=1)
        def status_style(val):
            if "🚨" in str(val):
                return "background-color: #ffcccc; font-weight: bold"
            elif "⚠️" in str(val):
                return "background-color: #fff3cd"
            return "background-color: #d4edda"
        st.dataframe(
            slow_open_df.style.map(status_style, subset=["status"]),
            use_container_width=True, hide_index=True,
        )

    st.divider()

    # --- Top 3 Recommendations ---
    st.subheader("📌 Top 3 Recommendations")
    st.caption("Based on combined workforce allocation, ticket demand, resolution performance, and cost data.")

    if USE_NEO4J:
        redeployment_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, count(e) AS headcount,
                 round(avg(e.total_allocation), 0) AS avg_alloc,
                 sum(CASE WHEN e.total_allocation < 80 THEN 1 ELSE 0 END) AS spare_staff,
                 collect(CASE WHEN e.total_allocation < 80 THEN e.name ELSE NULL END) AS spare_names
            OPTIONAL MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t2:Team {name: team})
            WITH team, headcount, avg_alloc, spare_staff,
                 [n IN spare_names WHERE n IS NOT NULL] AS spare_names,
                 count(tk) AS open_tickets
            RETURN team, headcount, avg_alloc, spare_staff, spare_names, open_tickets
            ORDER BY open_tickets DESC
        """, {"teams": team_filter})
    else:
        redeployment_df = mock_data.get_redeployment_data(team_filter)

    # Build recommendations from data
    if not redeployment_df.empty and not pressure_df.empty:
        recs = []

        # Rec 1: Redeploy from underutilised to critical
        critical_teams = pressure_df[pressure_df["pressure_status"] == "CRITICAL"]["team"].tolist()
        spare_rows = redeployment_df[redeployment_df["spare_staff"] > 0]
        if critical_teams and not spare_rows.empty:
            from_teams = []
            for _, r in spare_rows.iterrows():
                names = r["spare_names"]
                if isinstance(names, list) and names:
                    from_teams.append(f"{', '.join(names)} ({r['team']}, {int(r['avg_alloc'])}% avg)")
            if from_teams:
                recs.append({
                    "priority": "1",
                    "action": "Redeploy underutilised staff to critical teams",
                    "detail": f"**Move to:** {', '.join(critical_teams)} (over-committed + open tickets).\n\n"
                              f"**Available:** {'; '.join(from_teams)}.\n\n"
                              f"This is the lowest-cost intervention — no recruitment needed, immediate impact.",
                    "icon": "🔄",
                })

        # Rec 2: Automate access requests
        if not auto_df.empty:
            high_auto = auto_df[auto_df["automation_fit"] == "HIGH"]
            if not high_auto.empty:
                saving = high_auto["potential_saving"].sum()
                cats = ", ".join(high_auto["category"].str.replace("_", " ").str.title().tolist())
                recs.append({
                    "priority": "2",
                    "action": f"Automate {cats}",
                    "detail": f"**Saving:** £{int(saving):,}/yr. "
                              f"Highest volume, most predictable process (stddev <1 day). "
                              f"Implement self-service portal with automated provisioning. "
                              f"Frees IT Service Desk capacity for the 3 open tickets they're currently struggling with.",
                    "icon": "🤖",
                })

        # Rec 3: Address team fragility
        if 'fragility_df' not in dir():
            if USE_NEO4J:
                fragility_df_rec = run_query("""
                    MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                    WHERE t.name IN $teams
                    WITH t.name AS team, count(e) AS headcount,
                         round(100.0 / count(e), 0) AS absence_impact_pct
                    RETURN team, headcount, absence_impact_pct
                    ORDER BY absence_impact_pct DESC LIMIT 2
                """, {"teams": team_filter})
            else:
                fragility_df_rec = mock_data.get_team_fragility(team_filter).head(2)
        else:
            fragility_df_rec = fragility_df.head(2) if 'fragility_df' in dir() else pd.DataFrame()

        if not fragility_df_rec.empty:
            small_teams = fragility_df_rec[fragility_df_rec["headcount"] <= 3]
            if not small_teams.empty:
                team_names = ", ".join(small_teams["team"].tolist())
                recs.append({
                    "priority": "3",
                    "action": f"Cross-train or add resilience to {team_names}",
                    "detail": f"**Risk:** These teams have only {small_teams['headcount'].iloc[0]} people — "
                              f"one absence removes {int(small_teams['absence_impact_pct'].iloc[0])}% of capacity. "
                              f"Both have open high-priority tickets. "
                              f"Options: cross-skill from adjacent teams, establish buddy cover, or business-case a new post.",
                    "icon": "🛡️",
                })

        for rec in recs:
            with st.container(border=True):
                st.markdown(f"{rec['icon']} **Recommendation {rec['priority']}: {rec['action']}**")
                st.markdown(rec["detail"])

        if not recs:
            st.info("No specific recommendations — all teams within normal parameters.")

    st.divider()

    # Org hierarchy
    st.subheader("Reporting Structure")
    if USE_NEO4J:
        hierarchy_df = run_query("""
            MATCH (e:Employee)-[:REPORTS_TO]->(mgr:Employee)
            MATCH (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN mgr.name AS manager, mgr.role AS role,
                   collect(e.name) AS direct_reports, count(e) AS report_count
            ORDER BY report_count DESC
        """, {"teams": team_filter})
    else:
        hierarchy_df = mock_data.get_hierarchy(team_filter)
    if not hierarchy_df.empty:
        for _, row in hierarchy_df.iterrows():
            with st.expander(f"**{row['manager']}** — {row['role']} ({row['report_count']} reports)"):
                for name in row["direct_reports"]:
                    st.write(f"  • {name}")

    # Tenure analysis
    st.subheader("Tenure Analysis")
    if USE_NEO4J:
        tenure_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH e.name AS name, e.role AS role, t.name AS team, e.start_date AS start_date,
                 duration.between(date(e.start_date), date()).years AS years,
                 duration.between(date(e.start_date), date()).months AS total_months
            RETURN name, role, team, start_date,
                   years AS years_service,
                   total_months % 12 AS remaining_months,
                   CASE
                     WHEN total_months < 12 THEN 'New (<1yr)'
                     WHEN total_months < 24 THEN 'Developing (1-2yr)'
                     WHEN total_months < 48 THEN 'Established (2-4yr)'
                     ELSE 'Long-serving (4yr+)'
                   END AS tenure_band
            ORDER BY total_months DESC
        """, {"teams": team_filter})
    else:
        tenure_df = mock_data.get_tenure(team_filter)
    if not tenure_df.empty:
        col_tenure_chart, col_tenure_table = st.columns(2)
        with col_tenure_chart:
            band_counts = tenure_df.groupby("tenure_band").size().reset_index(name="count")
            band_order = ["New (<1yr)", "Developing (1-2yr)", "Established (2-4yr)", "Long-serving (4yr+)"]
            chart = alt.Chart(band_counts).mark_arc(innerRadius=50).encode(
                theta=alt.Theta("count:Q"),
                color=alt.Color("tenure_band:N", title="Tenure",
                                sort=band_order,
                                scale=alt.Scale(domain=band_order,
                                                range=["#e74c3c", "#f39c12", "#2ecc71", "#3498db"])),
                tooltip=["tenure_band", "count"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        with col_tenure_table:
            st.dataframe(
                tenure_df[["name", "role", "team", "years_service", "tenure_band"]],
                use_container_width=True, hide_index=True, height=300,
            )

    st.divider()

    # Location distribution
    st.subheader("Staff by Location")
    if USE_NEO4J:
        location_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN e.location AS location, count(e) AS headcount
            ORDER BY headcount DESC
        """, {"teams": team_filter})
    else:
        location_df = mock_data.get_location(team_filter)
    if not location_df.empty:
        chart = alt.Chart(location_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("location:N", sort="-y", title="Location"),
            y=alt.Y("headcount:Q", title="Headcount"),
            color=alt.Color("location:N", legend=None),
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)


# ===================== TAB 2: CAPACITY =====================
with tab2:
    st.subheader("Team Capacity Overview")
    if USE_NEO4J:
        capacity_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team,
                 count(e) AS headcount,
                 round(avg(e.total_allocation), 0) AS avg_allocation,
                 min(e.total_allocation) AS min_allocation,
                 max(e.total_allocation) AS max_allocation,
                 sum(CASE WHEN e.total_allocation > 100 THEN 1 ELSE 0 END) AS overloaded
            RETURN team, headcount, avg_allocation, min_allocation, max_allocation, overloaded
            ORDER BY avg_allocation DESC
        """, {"teams": team_filter})
    else:
        capacity_df = mock_data.get_capacity(team_filter)
    if not capacity_df.empty:
        chart = alt.Chart(capacity_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("team:N", sort="-y", title="Team"),
            y=alt.Y("avg_allocation:Q", title="Avg Allocation %"),
            color=alt.condition(
                alt.datum.avg_allocation > 100,
                alt.value("#e74c3c"),
                alt.value("#2ecc71")
            ),
        ).properties(height=300)
        rule = alt.Chart(pd.DataFrame({"y": [100]})).mark_rule(color="orange", strokeDash=[5, 5]).encode(y="y:Q")
        st.altair_chart(chart + rule, use_container_width=True)
        st.dataframe(capacity_df, use_container_width=True, hide_index=True)

    st.divider()

    col_over, col_under = st.columns(2)

    with col_over:
        st.subheader("🔴 Overloaded Staff")
        if USE_NEO4J:
            over_df = run_query("""
                MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams AND e.total_allocation > 100
                RETURN e.name AS name, e.role AS role, t.name AS team,
                       e.total_allocation AS allocation
                ORDER BY e.total_allocation DESC
            """, {"teams": team_filter})
        else:
            over_df = mock_data.get_overloaded(team_filter)
        if not over_df.empty:
            st.dataframe(over_df, use_container_width=True, hide_index=True)
        else:
            st.success("No overloaded staff!")

    with col_under:
        st.subheader("🟢 Available Capacity")
        if USE_NEO4J:
            under_df = run_query("""
                MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams AND e.total_allocation < 80
                RETURN e.name AS name, e.role AS role, t.name AS team,
                       e.total_allocation AS allocation,
                       (100 - e.total_allocation) AS spare_capacity
                ORDER BY spare_capacity DESC
            """, {"teams": team_filter})
        else:
            under_df = mock_data.get_underutilised(team_filter)
        if not under_df.empty:
            st.dataframe(under_df, use_container_width=True, hide_index=True)
        else:
            st.info("Everyone is at or above 80% allocation.")

    st.divider()

    # --- Project fragmentation warning ---
    st.subheader("🔀 Project Fragmentation Warning")
    st.caption("People spread across 3+ projects — context-switching risk regardless of total allocation")
    if USE_NEO4J:
        frag_df = run_query("""
            MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH e.name AS name, e.role AS role, t.name AS team,
                 e.total_allocation AS allocation,
                 count(p) AS project_count,
                 collect(p.name + ' (' + toString(a.percentage) + '%)') AS projects,
                 round(avg(a.percentage), 0) AS avg_slice
            WHERE project_count >= 3
            RETURN name, role, team, allocation, project_count, avg_slice, projects
            ORDER BY project_count DESC, allocation DESC
        """, {"teams": team_filter})
    else:
        frag_df = mock_data.get_project_fragmentation(team_filter)
    if not frag_df.empty:
        st.metric("People on 3+ projects", len(frag_df))
        col_frag_chart, col_frag_table = st.columns([1, 2])
        with col_frag_chart:
            chart = alt.Chart(frag_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("name:N", sort="-y", title=""),
                y=alt.Y("project_count:Q", title="Number of Projects"),
                color=alt.condition(
                    alt.datum.project_count > 3,
                    alt.value("#e74c3c"),
                    alt.value("#f39c12")
                ),
                tooltip=["name", "role", "team", "project_count", "avg_slice", "allocation"],
            ).properties(height=300)
            rule = alt.Chart(pd.DataFrame({"y": [3]})).mark_rule(color="orange", strokeDash=[5, 5]).encode(y="y:Q")
            st.altair_chart(chart + rule, use_container_width=True)
        with col_frag_table:
            st.dataframe(frag_df, use_container_width=True, hide_index=True)
        low_slice = frag_df[frag_df["avg_slice"] < 40]
        if not low_slice.empty:
            names = ", ".join(low_slice["name"].tolist())
            st.warning(f"⚠️ Thin-spread risk: {names} — avg project slice <40%. "
                       f"High context-switching overhead likely reduces effective output.")
    else:
        st.success("No one is spread across 3+ projects.")

    st.divider()
    st.subheader("Individual Workload Breakdown")
    if USE_NEO4J:
        workload_df = run_query("""
            MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN e.name AS name, t.name AS team, p.name AS project, a.percentage AS pct
            ORDER BY e.name, a.percentage DESC
        """, {"teams": team_filter})
    else:
        workload_df = mock_data.get_workload(team_filter)
    if not workload_df.empty:
        chart = alt.Chart(workload_df).mark_bar().encode(
            x=alt.X("pct:Q", title="Allocation %", stack="zero"),
            y=alt.Y("name:N", sort="-x", title=""),
            color=alt.Color("project:N", title="Project"),
            tooltip=["name", "team", "project", "pct"],
        ).properties(height=max(len(workload_df["name"].unique()) * 28, 200))
        rule = alt.Chart(pd.DataFrame({"x": [100]})).mark_rule(color="orange", strokeDash=[5, 5]).encode(x="x:Q")
        st.altair_chart(chart + rule, use_container_width=True)


# ===================== TAB 3: TICKETS =====================
with tab3:
    # --- Ageing open tickets ---
    st.subheader("🚨 Ageing Open Tickets")
    st.caption("How long each open ticket has been waiting — sorted by age")
    if USE_NEO4J:
        ageing_df = run_query("""
            MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams
            WITH tk, t, duration.between(date(tk.created_date), date()).days AS days_open
            RETURN tk.ticket_id AS ticket, t.name AS team, tk.category AS category,
                   tk.priority AS priority, tk.created_date AS created,
                   days_open,
                   CASE
                     WHEN days_open > 21 THEN 'Critical (>21d)'
                     WHEN days_open > 14 THEN 'Warning (>14d)'
                     WHEN days_open > 7 THEN 'Monitor (>7d)'
                     ELSE 'Recent (<7d)'
                   END AS age_band,
                   tk.description AS description
            ORDER BY days_open DESC
        """, {"teams": team_filter})
    else:
        ageing_df = mock_data.get_ageing_tickets(team_filter)
    if not ageing_df.empty:
        def age_color(val):
            colors = {
                "Critical (>21d)": "background-color: #e74c3c; color: white",
                "Warning (>14d)": "background-color: #ffcccc",
                "Monitor (>7d)": "background-color: #fff3cd",
                "Recent (<7d)": "background-color: #d4edda",
            }
            return colors.get(val, "")
        st.dataframe(
            ageing_df.style.map(age_color, subset=["age_band"]),
            use_container_width=True, hide_index=True,
        )
        # Ageing summary chart
        age_summary = ageing_df.groupby("age_band").size().reset_index(name="count")
        age_order = ["Critical (>21d)", "Warning (>14d)", "Monitor (>7d)", "Recent (<7d)"]
        chart = alt.Chart(age_summary).mark_arc(innerRadius=50).encode(
            theta=alt.Theta("count:Q"),
            color=alt.Color("age_band:N", title="Age Band", sort=age_order,
                            scale=alt.Scale(domain=age_order,
                                            range=["#e74c3c", "#ff7675", "#f39c12", "#2ecc71"])),
            tooltip=["age_band", "count"],
        ).properties(height=250)
        st.altair_chart(chart, use_container_width=True)
    else:
        st.success("No open tickets!")

    st.divider()

    col_vol, col_cat = st.columns(2)

    with col_vol:
        st.subheader("Ticket Volume by Team")
        if USE_NEO4J:
            vol_df = run_query("""
                MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
                WHERE t.name IN $teams
                WITH t.name AS team,
                     count(tk) AS total,
                     sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS open,
                     sum(CASE WHEN tk.status = 'resolved' THEN 1 ELSE 0 END) AS resolved
                RETURN team, total, open, resolved
                ORDER BY total DESC
            """, {"teams": team_filter})
        else:
            vol_df = mock_data.get_ticket_volume(team_filter)
        if not vol_df.empty:
            melted = vol_df.melt(id_vars=["team", "total"], value_vars=["open", "resolved"],
                                 var_name="status", value_name="count")
            chart = alt.Chart(melted).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("team:N", title="Team"),
                y=alt.Y("count:Q", title="Tickets"),
                color=alt.Color("status:N", scale=alt.Scale(domain=["open", "resolved"], range=["#e74c3c", "#2ecc71"])),
                tooltip=["team", "status", "count"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)

    with col_cat:
        st.subheader("Tickets by Category")
        if USE_NEO4J:
            cat_df = run_query("""
                MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
                WHERE t.name IN $teams
                RETURN tk.category AS category, count(tk) AS total,
                       sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS open
                ORDER BY total DESC
            """, {"teams": team_filter})
        else:
            cat_df = mock_data.get_ticket_categories(team_filter)
        if not cat_df.empty:
            chart = alt.Chart(cat_df).mark_arc(innerRadius=50).encode(
                theta=alt.Theta("total:Q"),
                color=alt.Color("category:N", title="Category"),
                tooltip=["category", "total", "open"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)

    st.divider()

    # Average resolution time
    st.subheader("⏱️ Average Resolution Time (days)")
    if USE_NEO4J:
        resolution_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams AND tk.status = 'resolved'
                  AND tk.resolved_date IS NOT NULL
            WITH t.name AS team, tk.category AS category,
                 duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days
            RETURN team, category,
                   round(avg(days), 1) AS avg_days,
                   min(days) AS min_days,
                   max(days) AS max_days,
                   count(*) AS tickets
            ORDER BY avg_days DESC
        """, {"teams": team_filter})
    else:
        resolution_df = mock_data.get_resolution_time(team_filter)
    if not resolution_df.empty:
        col_res_chart, col_res_table = st.columns(2)
        with col_res_chart:
            team_avg = resolution_df.groupby("team").apply(
                lambda g: round((g["avg_days"] * g["tickets"]).sum() / g["tickets"].sum(), 1)
            ).reset_index(name="avg_days")
            chart = alt.Chart(team_avg).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("team:N", sort="-y", title="Team"),
                y=alt.Y("avg_days:Q", title="Avg Days to Resolve"),
                color=alt.Color("team:N", legend=None),
                tooltip=["team", "avg_days"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        with col_res_table:
            st.dataframe(resolution_df, use_container_width=True, hide_index=True, height=300)

    st.divider()

    # --- Resolution time by priority ---
    st.subheader("🎯 Resolution Time by Priority")
    st.caption("Are high-priority tickets actually being resolved faster?")
    if USE_NEO4J:
        priority_res_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams AND tk.status = 'resolved'
                  AND tk.resolved_date IS NOT NULL
            WITH tk.priority AS priority,
                 duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days
            RETURN priority,
                   count(*) AS tickets,
                   round(avg(days), 1) AS avg_days,
                   min(days) AS min_days,
                   max(days) AS max_days
            ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
        """, {"teams": team_filter})
    else:
        priority_res_df = mock_data.get_resolution_by_priority(team_filter)
    if not priority_res_df.empty:
        col_pri_chart, col_pri_table = st.columns(2)
        with col_pri_chart:
            chart = alt.Chart(priority_res_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("priority:N", sort=["high", "medium", "low"], title="Priority"),
                y=alt.Y("avg_days:Q", title="Avg Days to Resolve"),
                color=alt.Color("priority:N", title="Priority",
                                scale=alt.Scale(domain=["high", "medium", "low"],
                                                range=["#e74c3c", "#f39c12", "#2ecc71"])),
                tooltip=["priority", "tickets", "avg_days", "min_days", "max_days"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        with col_pri_table:
            st.dataframe(priority_res_df, use_container_width=True, hide_index=True)
            if priority_res_df[priority_res_df["priority"] == "medium"]["avg_days"].values[0] > \
               priority_res_df[priority_res_df["priority"] == "high"]["avg_days"].values[0]:
                med_days = priority_res_df[priority_res_df["priority"] == "medium"]["avg_days"].values[0]
                high_days = priority_res_df[priority_res_df["priority"] == "high"]["avg_days"].values[0]
                st.warning(f"⚠️ Medium-priority tickets ({med_days}d) take longer than high-priority ({high_days}d) "
                           f"— suggests medium tickets lack urgency ownership and drift.")

    st.divider()

    # --- Category resolution variance ---
    st.subheader("📊 Category Resolution Consistency")
    st.caption("High variance = inconsistent process. Low variance = predictable.")
    if USE_NEO4J:
        variance_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams AND tk.status = 'resolved'
                  AND tk.resolved_date IS NOT NULL
            WITH tk.category AS category,
                 duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days
            RETURN category,
                   count(*) AS tickets,
                   round(avg(days), 1) AS avg_days,
                   min(days) AS min_days,
                   max(days) AS max_days,
                   max(days) - min(days) AS range_days,
                   round(stDev(days), 1) AS stddev_days
            ORDER BY stddev_days DESC
        """, {"teams": team_filter})
    else:
        variance_df = mock_data.get_resolution_variance(team_filter)
    if not variance_df.empty:
        col_var_chart, col_var_table = st.columns(2)
        with col_var_chart:
            # Range chart showing min-max spread per category
            bars = alt.Chart(variance_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("category:N", sort="-y", title="Category"),
                y=alt.Y("range_days:Q", title="Resolution Range (days)"),
                color=alt.condition(
                    alt.datum.stddev_days > 5,
                    alt.value("#e74c3c"),
                    alt.value("#2ecc71")
                ),
                tooltip=["category", "tickets", "avg_days", "min_days", "max_days", "stddev_days"],
            ).properties(height=300)
            st.altair_chart(bars, use_container_width=True)
        with col_var_table:
            st.dataframe(variance_df, use_container_width=True, hide_index=True)
            high_var = variance_df[variance_df["stddev_days"] > 5]
            if not high_var.empty:
                cats = ", ".join(high_var["category"].tolist())
                st.warning(f"⚠️ High variance in: {cats} — suggests inconsistent triage, "
                           f"unclear ownership, or dependency on external parties.")

    st.divider()

    # Backlog trend
    st.subheader("📈 Backlog Trend Over Time")
    if USE_NEO4J:
        trend_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams
            WITH tk.created_date AS date, 'created' AS event, t.name AS team
            RETURN date, event, team
            UNION ALL
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams AND tk.resolved_date IS NOT NULL
            WITH tk.resolved_date AS date, 'resolved' AS event, t.name AS team
            RETURN date, event, team
            ORDER BY date
        """, {"teams": team_filter})
        if not trend_df.empty:
            trend_df["date"] = pd.to_datetime(trend_df["date"])
            trend_df["delta"] = trend_df["event"].map({"created": 1, "resolved": -1})
            trend_df = trend_df.sort_values("date")
            trend_df["open_backlog"] = trend_df["delta"].cumsum()
            daily = trend_df.groupby("date").last().reset_index()[["date", "open_backlog"]]
        else:
            daily = pd.DataFrame()
    else:
        daily = mock_data.get_backlog_trend(team_filter)
    if not daily.empty:
        chart = alt.Chart(daily).mark_area(
            line={"color": "#3498db"},
            color=alt.Gradient(gradient="linear", stops=[
                alt.GradientStop(color="#3498db", offset=0),
                alt.GradientStop(color="rgba(52,152,219,0.1)", offset=1),
            ], x1=1, x2=1, y1=1, y2=0),
        ).encode(
            x=alt.X("date:T", title="Date"),
            y=alt.Y("open_backlog:Q", title="Open Backlog"),
            tooltip=["date:T", "open_backlog:Q"],
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)

    st.divider()
    st.subheader("Tickets Per Person Ratio")
    if USE_NEO4J:
        ratio_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, count(tk) AS total_tickets
            MATCH (e:Employee)-[:MEMBER_OF]->(t2:Team {name: team})
            WITH team, total_tickets, count(e) AS headcount
            RETURN team, headcount, total_tickets,
                   round(toFloat(total_tickets) / headcount, 1) AS tickets_per_person
            ORDER BY tickets_per_person DESC
        """, {"teams": team_filter})
    else:
        ratio_df = mock_data.get_tickets_per_person(team_filter)
    if not ratio_df.empty:
        chart = alt.Chart(ratio_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("team:N", sort="-y", title="Team"),
            y=alt.Y("tickets_per_person:Q", title="Tickets per Person"),
            color=alt.Color("team:N", legend=None),
            tooltip=["team", "headcount", "total_tickets", "tickets_per_person"],
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)


# ===================== TAB 4: SKILLS & RISK =====================
with tab4:
    # --- Team fragility score ---
    st.subheader("🏚️ Team Fragility Score")
    st.caption("How vulnerable is each team to losing a single person? Combines team size, unique skills concentration, and overallocation.")
    if USE_NEO4J:
        fragility_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, count(e) AS headcount,
                 round(100.0 / count(e), 0) AS absence_impact_pct
            OPTIONAL MATCH (e2:Employee)-[:MEMBER_OF]->(t2:Team {name: team})
            OPTIONAL MATCH (e2)-[:HAS_SKILL]->(s:Skill)
            WITH team, headcount, absence_impact_pct, s.name AS skill, count(e2) AS holders
            WITH team, headcount, absence_impact_pct,
                 sum(CASE WHEN holders = 1 THEN 1 ELSE 0 END) AS unique_skills
            RETURN team, headcount, absence_impact_pct, unique_skills,
                   round(absence_impact_pct * 0.4 + unique_skills * 0.6, 0) AS fragility_score
            ORDER BY fragility_score DESC
        """, {"teams": team_filter})
    else:
        fragility_df = mock_data.get_team_fragility(team_filter)
    if not fragility_df.empty:
        col_frag_score_chart, col_frag_score_table = st.columns(2)
        with col_frag_score_chart:
            fragility_df["risk_level"] = fragility_df["fragility_score"].apply(
                lambda x: "High" if x > 20 else "Medium" if x > 15 else "Low"
            )
            chart = alt.Chart(fragility_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X("team:N", sort="-y", title="Team"),
                y=alt.Y("fragility_score:Q", title="Fragility Score"),
                color=alt.Color("risk_level:N", title="Risk",
                                scale=alt.Scale(domain=["High", "Medium", "Low"],
                                                range=["#e74c3c", "#f39c12", "#2ecc71"])),
                tooltip=["team", "headcount", "absence_impact_pct", "unique_skills", "fragility_score"],
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        with col_frag_score_table:
            st.dataframe(fragility_df, use_container_width=True, hide_index=True)
            high_frag = fragility_df[fragility_df["fragility_score"] > 20]
            if not high_frag.empty:
                teams_at_risk = ", ".join(high_frag["team"].tolist())
                st.error(f"🚨 High fragility: {teams_at_risk} — small team size combined with "
                         f"concentrated unique skills. A single departure could severely impact delivery.")

    st.divider()

    # --- Per-person impact analysis ---
    st.subheader("👤 Individual Departure Impact")
    st.caption("What unique skills would be lost if each person left?")
    if USE_NEO4J:
        impact_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            OPTIONAL MATCH (e)-[:HAS_SKILL]->(s:Skill)
            WITH e, t, s
            OPTIONAL MATCH (other:Employee)-[:HAS_SKILL]->(s)
            WHERE other <> e
            WITH e.name AS name, e.role AS role, t.name AS team,
                 e.total_allocation AS allocation,
                 sum(CASE WHEN other IS NULL THEN 1 ELSE 0 END) AS unique_skills_lost,
                 collect(CASE WHEN other IS NULL THEN s.name ELSE NULL END) AS skills_at_risk
            WHERE unique_skills_lost > 0
            RETURN name, role, team, allocation, unique_skills_lost,
                   [s IN skills_at_risk WHERE s IS NOT NULL] AS skills_at_risk
            ORDER BY unique_skills_lost DESC
        """, {"teams": team_filter})
    else:
        impact_df = mock_data.get_departure_impact(team_filter)
    if not impact_df.empty:
        impact_df["risk_level"] = impact_df["unique_skills_lost"].apply(
            lambda x: "High" if x >= 4 else "Medium" if x >= 2 else "Low"
        )
        chart = alt.Chart(impact_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("unique_skills_lost:Q", title="Unique Skills Lost if They Leave"),
            y=alt.Y("name:N", sort="-x", title=""),
            color=alt.Color("risk_level:N", title="Risk",
                            scale=alt.Scale(domain=["High", "Medium", "Low"],
                                            range=["#e74c3c", "#f39c12", "#2ecc71"])),
            tooltip=["name", "role", "team", "unique_skills_lost"],
        ).properties(height=max(len(impact_df) * 28, 200))
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(impact_df, use_container_width=True, hide_index=True)
    else:
        st.success("No single-holder skill risks found.")

    st.divider()

    col_spof, col_search = st.columns(2)

    with col_spof:
        st.subheader("⚠️ Single Points of Failure")
        st.caption("Skills held by only one person in selected teams")
        if USE_NEO4J:
            spof_df = run_query("""
                MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams
                WITH s.name AS skill, collect(e.name) AS holders, count(e) AS count
                WHERE count = 1
                RETURN skill, holders[0] AS sole_holder
                ORDER BY skill
            """, {"teams": team_filter})
        else:
            spof_df = mock_data.get_spof(team_filter)
        if not spof_df.empty:
            st.dataframe(spof_df, use_container_width=True, hide_index=True, height=400)
        else:
            st.success("No single points of failure!")

    with col_search:
        st.subheader("🔍 Skill Search")
        if USE_NEO4J:
            skills_df = run_query("""
                MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams
                RETURN DISTINCT s.name AS skill ORDER BY skill
            """, {"teams": team_filter})
        else:
            skills_df = mock_data.get_all_skills(team_filter)
        if not skills_df.empty:
            selected_skill = st.selectbox("Find people with skill:", skills_df["skill"].tolist())
            if selected_skill:
                if USE_NEO4J:
                    skill_holders = run_query("""
                        MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill {name: $skill}),
                              (e)-[:MEMBER_OF]->(t:Team)
                        WHERE t.name IN $teams
                        RETURN e.name AS name, e.role AS role, t.name AS team,
                               e.total_allocation AS allocation
                        ORDER BY e.total_allocation ASC
                    """, {"skill": selected_skill, "teams": team_filter})
                else:
                    skill_holders = mock_data.get_skill_holders(selected_skill, team_filter)
                st.dataframe(skill_holders, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Grade Distribution")
    if USE_NEO4J:
        grade_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN t.name AS team, e.grade AS grade, count(e) AS count
            ORDER BY t.name, e.grade
        """, {"teams": team_filter})
    else:
        grade_df = mock_data.get_grade_distribution(team_filter)
    if not grade_df.empty:
        chart = alt.Chart(grade_df).mark_bar().encode(
            x=alt.X("team:N", title="Team"),
            y=alt.Y("count:Q", title="Count", stack="zero"),
            color=alt.Color("grade:N", title="Grade",
                            sort=["AO", "EO", "HEO", "SEO", "G7", "G6"]),
            tooltip=["team", "grade", "count"],
        ).properties(height=350)
        st.altair_chart(chart, use_container_width=True)


# ===================== TAB 5: PROJECTS =====================
with tab5:
    st.subheader("Project Staffing & Effort")
    if USE_NEO4J:
        proj_df = run_query("""
            MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH p.name AS project, count(DISTINCT e) AS people,
                 sum(a.percentage) AS total_effort
            RETURN project, people, total_effort
            ORDER BY total_effort DESC
        """, {"teams": team_filter})
    else:
        proj_df = mock_data.get_project_effort(team_filter)
    if not proj_df.empty:
        chart = alt.Chart(proj_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("project:N", sort="-y", title="Project"),
            y=alt.Y("total_effort:Q", title="Total Effort %"),
            color=alt.Color("project:N", legend=None),
            tooltip=["project", "people", "total_effort"],
        ).properties(height=350)
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(proj_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Cross-Team Dependencies")
    st.caption("Projects staffed from multiple teams")
    if USE_NEO4J:
        cross_df = run_query("""
            MATCH (e:Employee)-[:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH p.name AS project, collect(DISTINCT t.name) AS teams, count(DISTINCT t) AS team_count
            WHERE team_count > 1
            RETURN project, team_count, teams
            ORDER BY team_count DESC
        """, {"teams": team_filter})
    else:
        cross_df = mock_data.get_cross_team(team_filter)
    if not cross_df.empty:
        st.dataframe(cross_df, use_container_width=True, hide_index=True)
    else:
        st.info("No cross-team project dependencies found.")

    st.divider()
    st.subheader("Project Detail")
    if not proj_df.empty:
        selected_project = st.selectbox("Select project:", proj_df["project"].tolist())
        if selected_project:
            if USE_NEO4J:
                detail_df = run_query("""
                    MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project {name: $project}),
                          (e)-[:MEMBER_OF]->(t:Team)
                    WHERE t.name IN $teams
                    RETURN e.name AS name, e.role AS role, t.name AS team,
                           a.percentage AS allocation
                    ORDER BY a.percentage DESC
                """, {"project": selected_project, "teams": team_filter})
            else:
                detail_df = mock_data.get_project_detail(selected_project, team_filter)
            st.dataframe(detail_df, use_container_width=True, hide_index=True)


# ===================== TAB 6: COST & BUDGET =====================
with tab6:
    # --- KPI row ---
    if USE_NEO4J:
        cost_summary = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN sum(e.full_cost) AS total_cost,
                   sum(e.annual_salary) AS total_salary,
                   round(avg(e.full_cost), 0) AS avg_cost,
                   sum(e.full_cost) - sum(e.annual_salary) AS total_on_costs
        """, {"teams": team_filter})
    else:
        cost_summary = mock_data.get_cost_summary(team_filter)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Annual Cost", f"£{int(cost_summary['total_cost'].iloc[0]):,}")
    c2.metric("Total Salary", f"£{int(cost_summary['total_salary'].iloc[0]):,}")
    c3.metric("Total On-Costs", f"£{int(cost_summary['total_on_costs'].iloc[0]):,}")
    c4.metric("Avg Cost per Head", f"£{int(cost_summary['avg_cost'].iloc[0]):,}")

    st.divider()

    # --- Team cost breakdown ---
    st.subheader("💷 Cost by Team")
    if USE_NEO4J:
        team_cost_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, count(e) AS headcount,
                 sum(e.full_cost) AS total_cost,
                 sum(e.annual_salary) AS total_salary,
                 round(avg(e.full_cost), 0) AS avg_cost_per_head
            RETURN team, headcount, total_salary, total_cost, avg_cost_per_head
            ORDER BY total_cost DESC
        """, {"teams": team_filter})
    else:
        team_cost_df = mock_data.get_team_costs(team_filter)
    if not team_cost_df.empty:
        chart = alt.Chart(team_cost_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("team:N", sort="-y", title="Team"),
            y=alt.Y("total_cost:Q", title="Total Annual Cost (£)"),
            color=alt.Color("team:N", legend=None),
            tooltip=["team", "headcount", "total_salary", "total_cost", "avg_cost_per_head"],
        ).properties(height=300)
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(team_cost_df, use_container_width=True, hide_index=True)

    st.divider()

    # --- Project cost allocation ---
    col_proj_cost, col_proj_chart = st.columns(2)

    with col_proj_cost:
        st.subheader("📁 Cost Allocated to Projects")
        st.caption("Based on each person's allocation % × their full annual cost")
        if USE_NEO4J:
            proj_cost_df = run_query("""
                MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams
                WITH p.name AS project,
                     count(DISTINCT e) AS people,
                     sum(toInteger(e.full_cost * a.percentage / 100.0)) AS allocated_cost
                RETURN project, people, allocated_cost
                ORDER BY allocated_cost DESC
            """, {"teams": team_filter})
        else:
            proj_cost_df = mock_data.get_project_costs(team_filter)
        if not proj_cost_df.empty:
            st.dataframe(proj_cost_df, use_container_width=True, hide_index=True, height=400)

    with col_proj_chart:
        st.subheader("Project Cost Distribution")
        if not proj_cost_df.empty:
            chart = alt.Chart(proj_cost_df).mark_arc(innerRadius=50).encode(
                theta=alt.Theta("allocated_cost:Q"),
                color=alt.Color("project:N", title="Project"),
                tooltip=["project", "people", "allocated_cost"],
            ).properties(height=400)
            st.altair_chart(chart, use_container_width=True)

    st.divider()

    # --- Cost per ticket (efficiency) ---
    st.subheader("📊 Cost Efficiency — Cost per Ticket by Team")
    st.caption("Team's total cost ÷ tickets handled = cost per ticket")
    if USE_NEO4J:
        cost_per_ticket_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH t.name AS team, sum(e.full_cost) AS team_cost
            OPTIONAL MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t2:Team {name: team})
            WITH team, team_cost, count(tk) AS tickets
            WHERE tickets > 0
            RETURN team, team_cost, tickets,
                   toInteger(team_cost / tickets) AS cost_per_ticket
            ORDER BY cost_per_ticket DESC
        """, {"teams": team_filter})
    else:
        cost_per_ticket_df = mock_data.get_cost_per_ticket(team_filter)
    if not cost_per_ticket_df.empty:
        chart = alt.Chart(cost_per_ticket_df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("team:N", sort="-y", title="Team"),
            y=alt.Y("cost_per_ticket:Q", title="Cost per Ticket (£)"),
            color=alt.condition(
                alt.datum.cost_per_ticket > cost_per_ticket_df["cost_per_ticket"].mean(),
                alt.value("#e74c3c"),
                alt.value("#2ecc71")
            ),
            tooltip=["team", "team_cost", "tickets", "cost_per_ticket"],
        ).properties(height=300)
        avg_line = alt.Chart(pd.DataFrame({"y": [cost_per_ticket_df["cost_per_ticket"].mean()]})).mark_rule(
            color="orange", strokeDash=[5, 5]
        ).encode(y="y:Q")
        st.altair_chart(chart + avg_line, use_container_width=True)
        st.dataframe(cost_per_ticket_df, use_container_width=True, hide_index=True)

    st.divider()

    # --- Individual cost roster ---
    st.subheader("👤 Individual Cost Roster")
    if USE_NEO4J:
        roster_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN e.name AS name, e.role AS role, e.grade AS grade, t.name AS team,
                   e.annual_salary AS salary, e.full_cost AS full_cost, e.day_rate AS day_rate,
                   e.total_allocation AS allocation
            ORDER BY e.full_cost DESC
        """, {"teams": team_filter})
    else:
        roster_df = mock_data.get_cost_roster(team_filter)
    if not roster_df.empty:
        st.dataframe(roster_df, use_container_width=True, hide_index=True)

    st.divider()

    # --- Wasted spend (overallocation) ---
    st.subheader("⚠️ Overallocation Cost — Potential Overtime/Burnout Spend")
    st.caption("Cost of effort above 100% allocation — indicates hidden overtime or unsustainable workload")
    if USE_NEO4J:
        waste_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams AND e.total_allocation > 100
            WITH e.name AS name, e.role AS role, t.name AS team,
                 e.total_allocation AS allocation, e.full_cost AS full_cost,
                 toInteger(e.full_cost * (e.total_allocation - 100) / 100.0) AS excess_cost
            RETURN name, role, team, allocation, full_cost, excess_cost
            ORDER BY excess_cost DESC
        """, {"teams": team_filter})
    else:
        waste_df = mock_data.get_overallocation_cost(team_filter)
    if not waste_df.empty:
        total_excess = waste_df["excess_cost"].sum()
        st.metric("Total Excess Cost (overallocation)", f"£{int(total_excess):,}")
        st.dataframe(waste_df, use_container_width=True, hide_index=True)
    else:
        st.success("No overallocated staff — no excess cost.")


# ===================== TAB 7: AUTOMATION =====================
with tab7:
    st.subheader("🤖 Automation Opportunity Assessment")
    st.caption("Data-driven analysis of which operational processes are candidates for automation, ranked by impact.")

    if not auto_df.empty:
        total_saving = auto_df["potential_saving"].sum()

        # KPI row
        ac1, ac2, ac3 = st.columns(3)
        high_count = len(auto_df[auto_df["automation_fit"] == "HIGH"])
        med_count = len(auto_df[auto_df["automation_fit"] == "MEDIUM"])
        ac1.metric("High-Fit Candidates", high_count)
        ac2.metric("Medium-Fit Candidates", med_count)
        ac3.metric("Total Potential Saving", f"£{int(total_saving):,}/yr")

        st.divider()

        # --- The director's 2-minute view ---
        st.subheader("🎯 Recommendation Summary")
        for _, row in auto_df.iterrows():
            fit = row["automation_fit"]
            if fit == "HIGH":
                icon = "🟢"
                label = "Automate now"
            elif fit == "MEDIUM":
                icon = "🟡"
                label = "Investigate"
            else:
                icon = "🔴"
                label = "Not suitable"

            cat_display = row["category"].replace("_", " ").title()
            with st.container(border=True):
                rc1, rc2, rc3, rc4 = st.columns([3, 1, 1, 1])
                rc1.markdown(f"{icon} **{cat_display}** ({row['team']}) — {label}")
                rc2.metric("Volume", f"{int(row['volume'])} tickets")
                rc3.metric("Avg Resolution", f"{row['avg_days']}d")
                rc4.metric("Saving", f"£{int(row['potential_saving']):,}/yr")

                if fit == "HIGH":
                    st.caption(
                        f"Predictable process (stddev {row['stddev']}d, range {int(row['min_days'])}–{int(row['max_days'])}d). "
                        f"{int(row['low_priority_pct'])}% low priority. "
                        f"High volume, low complexity — strong candidate for workflow automation or self-service."
                    )
                elif fit == "MEDIUM":
                    st.caption(
                        f"Moderate consistency (stddev {row['stddev']}d, range {int(row['min_days'])}–{int(row['max_days'])}d). "
                        f"Some tickets may be automatable but others require judgement. "
                        f"Consider triaging into simple (automate) vs complex (manual) sub-categories."
                    )
                else:
                    st.caption(
                        f"High variance (stddev {row['stddev']}d, range {int(row['min_days'])}–{int(row['max_days'])}d). "
                        f"Unpredictable resolution suggests case-by-case judgement required. "
                        f"Focus on process standardisation before automation."
                    )

        st.divider()

        # --- Evidence chart ---
        st.subheader("📊 Evidence — Volume vs Predictability")
        st.caption("Best automation candidates: top-left (high volume, low variance)")
        bubble = alt.Chart(auto_df).mark_circle().encode(
            x=alt.X("stddev:Q", title="Resolution Variance (stddev days) → less predictable",
                    scale=alt.Scale(domain=[-1, auto_df["stddev"].max() + 2])),
            y=alt.Y("volume:Q", title="↑ Ticket Volume"),
            size=alt.Size("potential_saving:Q", title="Potential Saving (£)", scale=alt.Scale(range=[100, 800])),
            color=alt.Color("automation_fit:N", title="Fit",
                            scale=alt.Scale(domain=["HIGH", "MEDIUM", "LOW"],
                                            range=["#2ecc71", "#f39c12", "#e74c3c"])),
            tooltip=["category", "team", "volume", "avg_days", "stddev", "potential_saving", "automation_fit"],
        ).properties(height=350)
        text = alt.Chart(auto_df).mark_text(dy=-15, fontSize=11, fontWeight="bold").encode(
            x=alt.X("stddev:Q"),
            y=alt.Y("volume:Q"),
            text=alt.Text("category:N"),
        )
        st.altair_chart(bubble + text, use_container_width=True)

        st.divider()

        # --- Full data ---
        st.subheader("📝 Full Assessment Data")
        st.dataframe(
            auto_df.style.map(
                lambda v: {"HIGH": "background-color: #d4edda", "MEDIUM": "background-color: #fff3cd",
                           "LOW": "background-color: #ffcccc"}.get(v, ""),
                subset=["automation_fit"]
            ),
            use_container_width=True, hide_index=True,
        )

    st.divider()
    st.subheader("🚀 What We'd Need to Go Further")
    st.caption("Data gaps that would unlock the next level of insight.")
    with st.container(border=True):
        st.markdown("""
| Data Source | What It Unlocks | Priority |
|---|---|---|
| **Absence / leave records** | Real-time availability, absence rate by team, seasonal patterns | High |
| **Vacancy & attrition data** | Predict capacity gaps before they happen, time-to-fill metrics | High |
| **Training & compliance records** | Mandatory training compliance, security clearance expiry alerts | Medium |
| **Permanent vs contractor status** | Workforce mix analysis, contractor dependency risk, cost comparison | Medium |
| **SLA definitions per category** | Breach tracking, SLA compliance %, automated escalation triggers | Medium |
| **Time-tracking / effort logs** | Actual vs allocated time, identify where estimates are wrong | Low |
| **Historical ticket data (12+ months)** | Seasonal demand patterns, year-on-year trend, forecasting | Low |
""")


# ===================== TAB 8: CHAT =====================
with tab8:

    def _render_chart(df, chart_type, **kwargs):
        if df is None or df.empty:
            return
        if chart_type == "bar_h" and "x_col" in kwargs and "y_col" in kwargs:
            chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X(f"{kwargs['x_col']}:Q", title=kwargs.get("x_title", "")),
                y=alt.Y(f"{kwargs['y_col']}:N", sort="-x", title=""),
                color=alt.Color(f"{kwargs.get('color_col', kwargs['y_col'])}:N", legend=None),
                tooltip=list(df.columns),
            ).properties(height=max(len(df) * 28, 200))
            st.altair_chart(chart, use_container_width=True)
        elif chart_type == "bar_v" and "x_col" in kwargs and "y_col" in kwargs:
            chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
                x=alt.X(f"{kwargs['x_col']}:N", sort="-y", title=""),
                y=alt.Y(f"{kwargs['y_col']}:Q", title=kwargs.get("y_title", "")),
                color=alt.Color(f"{kwargs.get('color_col', kwargs['x_col'])}:N", legend=None),
                tooltip=list(df.columns),
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)
        elif chart_type == "scatter" and "x_col" in kwargs and "y_col" in kwargs:
            scatter = alt.Chart(df).mark_circle(size=200).encode(
                x=alt.X(f"{kwargs['x_col']}:Q", title=kwargs.get("x_title", "")),
                y=alt.Y(f"{kwargs['y_col']}:Q", title=kwargs.get("y_title", "")),
                color=alt.Color(f"{kwargs.get('color_col', kwargs['x_col'])}:N", title="Status",
                                scale=alt.Scale(domain=["CRITICAL","AT RISK","OVER-COMMITTED","OK"],
                                                range=["#e74c3c","#f39c12","#e67e22","#2ecc71"])),
                tooltip=list(df.columns),
            ).properties(height=300)
            text = alt.Chart(df).mark_text(dy=-15, fontSize=11, fontWeight="bold").encode(
                x=alt.X(f"{kwargs['x_col']}:Q"), y=alt.Y(f"{kwargs['y_col']}:Q"),
                text=f"{kwargs.get('label_col', kwargs['x_col'])}:N",
            )
            st.altair_chart(scatter + text, use_container_width=True)
        elif chart_type == "arc" and "theta_col" in kwargs and "color_col" in kwargs:
            chart = alt.Chart(df).mark_arc(innerRadius=50).encode(
                theta=alt.Theta(f"{kwargs['theta_col']}:Q"),
                color=alt.Color(f"{kwargs['color_col']}:N"),
                tooltip=list(df.columns),
            ).properties(height=300)
            st.altair_chart(chart, use_container_width=True)

    def _render_response(msg):
        st.markdown(msg["text"])
        if msg.get("df") is not None and not msg["df"].empty:
            ct = msg.get("chart_type")
            ck = msg.get("chart_kwargs", {})
            if ct:
                _render_chart(msg["df"], ct, **ck)
            st.dataframe(msg["df"], use_container_width=True, hide_index=True)

    # Chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Two-column layout: left = examples + input, right = conversation
    chat_left, chat_right = st.columns([1, 3])

    with chat_left:
        st.subheader("💬 Ask a Question")
        st.markdown("""
**People & Capacity**
- Who is overloaded?
- Who has spare capacity?
- Which teams are under pressure?

**Tickets & Operations**
- Show me open tickets
- Show resolution times
- Which categories take longest?

**Skills & Risk**
- What are the single points of failure?
- Who has Python skills?
- Show team fragility

**Cost & Budget**
- What is the total cost?
- Which projects cost the most?

**Recommendations**
- What are the top recommendations?
- What can we automate?

**Projects**
- Who is on Case Management Modernisation?
""")

    with chat_right:
        # Display chat history
        chat_container = st.container(height=600)
        with chat_container:
            if not st.session_state.chat_history:
                st.info("👈 Ask a question using the input below, or click an example from the left panel.")
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    _render_response(msg)

    # Chat input at full width below
    question = st.chat_input("Ask about your workforce, tickets, costs, or skills...")

    if question:
        st.session_state.chat_history.append({"role": "user", "text": question, "df": None, "chart_type": None, "chart_kwargs": {}})

        q = question.lower()
        answer_text = ""
        answer_df = None
        chart_type = None
        chart_kwargs = {}

        # --- Pattern matching ---
        if any(w in q for w in ["overloaded", "over-committed", "overworked", "burnout", "over capacity"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                    WHERE e.total_allocation > 100
                    RETURN e.name AS name, e.role AS role, t.name AS team,
                           e.total_allocation AS allocation
                    ORDER BY e.total_allocation DESC
                """)
            else:
                answer_df = mock_data.get_overloaded(team_filter)
            answer_text = f"**{len(answer_df)} staff are allocated above 100%:**"
            chart_type = "bar_h"
            chart_kwargs = {"x_col": "allocation", "y_col": "name", "x_title": "Allocation %"}

        elif any(w in q for w in ["pressure", "critical", "at risk", "struggling"]):
            if USE_NEO4J:
                answer_df = pressure_df
            else:
                answer_df = mock_data.get_pressure_view(team_filter)
            answer_text = "**Combined pressure view — workforce allocation × operational demand:**"
            chart_type = "scatter"
            chart_kwargs = {"x_col": "avg_allocation", "y_col": "tickets_per_person",
                            "x_title": "Avg Allocation %", "y_title": "Tickets per Person",
                            "color_col": "pressure_status", "label_col": "team"}

        elif any(w in q for w in ["open ticket", "backlog", "ageing", "aging", "outstanding"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team)
                    WITH tk, t, duration.between(date(tk.created_date), date()).days AS days_open
                    RETURN tk.ticket_id AS ticket, t.name AS team, tk.category AS category,
                           tk.priority AS priority, days_open, tk.description AS description
                    ORDER BY days_open DESC
                """)
            else:
                answer_df = mock_data.get_ageing_tickets(team_filter)
            answer_text = f"**{len(answer_df)} open tickets:**"
            chart_type = "bar_h"
            chart_kwargs = {"x_col": "days_open", "y_col": "ticket", "x_title": "Days Open", "color_col": "team"}

        elif any(w in q for w in ["single point", "spof", "failure", "sole holder"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                    WITH s.name AS skill, collect(e.name) AS holders, count(e) AS count
                    WHERE count = 1
                    RETURN skill, holders[0] AS sole_holder
                    ORDER BY skill
                """)
            else:
                answer_df = mock_data.get_spof(team_filter)
            answer_text = f"**{len(answer_df)} skills held by only one person:**"

        elif any(w in q for w in ["skill", "python", "aws", "sql", "react", "power bi", "who knows", "who has"]):
            # Extract skill name
            known_skills = ["python", "aws", "sql", "react", "power bi", "docker", "typescript",
                            "excel", "oracle", "cyber security", "agile", "procurement", "itil"]
            skill_match = None
            for s in known_skills:
                if s in q:
                    skill_match = s
                    break
            if skill_match:
                skill_name = skill_match.title() if skill_match not in ["aws", "sql", "itil"] else skill_match.upper()
                # Try exact match first, then case-insensitive
                if USE_NEO4J:
                    answer_df = run_query("""
                        MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                        WHERE toLower(s.name) = toLower($skill)
                        RETURN e.name AS name, e.role AS role, t.name AS team,
                               e.total_allocation AS allocation
                        ORDER BY e.total_allocation ASC
                    """, {"skill": skill_name})
                    if answer_df.empty:
                        answer_df = run_query("""
                            MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                            WHERE toLower(s.name) CONTAINS toLower($skill)
                            RETURN e.name AS name, e.role AS role, t.name AS team,
                                   s.name AS skill, e.total_allocation AS allocation
                            ORDER BY e.total_allocation ASC
                        """, {"skill": skill_match})
                else:
                    answer_df = mock_data.get_skill_holders(skill_name, team_filter)
                    if answer_df.empty:
                        answer_df = mock_data.get_skill_holders(skill_match, team_filter)
                answer_text = f"**People with '{skill_match}' skills (sorted by availability):**"
                chart_type = "bar_h"
                chart_kwargs = {"x_col": "allocation", "y_col": "name", "x_title": "Allocation %"}
            else:
                if USE_NEO4J:
                    answer_df = run_query("""
                        MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
                        RETURN DISTINCT s.name AS skill ORDER BY skill
                    """)
                else:
                    answer_df = mock_data.get_all_skills(team_filter)
                answer_text = f"**{len(answer_df)} skills in the organisation. Ask about a specific one, e.g. 'Who has Python skills?'**"

        elif any(w in q for w in ["project cost", "cost by project", "project spend", "expensive project"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
                    WITH p.name AS project, count(DISTINCT e) AS people,
                         sum(toInteger(e.full_cost * a.percentage / 100.0)) AS allocated_cost
                    RETURN project, people, allocated_cost
                    ORDER BY allocated_cost DESC
                """)
            else:
                answer_df = mock_data.get_project_costs(team_filter)
            answer_text = "**Cost allocated to each project (person cost × allocation %):**"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "project", "y_col": "allocated_cost", "y_title": "Allocated Cost (£)"}

        elif any(w in q for w in ["total cost", "annual cost", "how much", "budget"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                    WITH t.name AS team, count(e) AS headcount,
                         sum(e.full_cost) AS total_cost,
                         round(avg(e.full_cost), 0) AS avg_per_head
                    RETURN team, headcount, total_cost, avg_per_head
                    ORDER BY total_cost DESC
                """)
            else:
                answer_df = mock_data.get_team_costs(team_filter)
            total = answer_df["total_cost"].sum()
            answer_text = f"**Total annual cost: £{int(total):,}** — breakdown by team:"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "team", "y_col": "total_cost", "y_title": "Total Cost (£)"}

        elif any(w in q for w in ["spare", "available", "capacity", "underutilised", "free"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                    WHERE e.total_allocation < 80
                    RETURN e.name AS name, e.role AS role, t.name AS team,
                           e.total_allocation AS allocation,
                           (100 - e.total_allocation) AS spare_capacity
                    ORDER BY spare_capacity DESC
                """)
            else:
                answer_df = mock_data.get_underutilised(team_filter)
            answer_text = f"**{len(answer_df)} staff with spare capacity (<80% allocated):**"
            chart_type = "bar_h"
            chart_kwargs = {"x_col": "spare_capacity", "y_col": "name", "x_title": "Spare Capacity %"}

        elif any(w in q for w in ["fragil", "vulnerable", "resilience", "bus factor"]):
            if USE_NEO4J:
                answer_df = fragility_df if 'fragility_df' in dir() else run_query("""
                    MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
                    WITH t.name AS team, count(e) AS headcount,
                         round(100.0 / count(e), 0) AS absence_impact_pct
                    RETURN team, headcount, absence_impact_pct
                    ORDER BY absence_impact_pct DESC
                """)
            else:
                answer_df = mock_data.get_team_fragility(team_filter)
            answer_text = "**Team fragility — how vulnerable each team is to losing one person:**"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "team", "y_col": "fragility_score", "y_title": "Fragility Score"}

        elif any(w in q for w in ["automat", "self-service", "efficiency"]):
            answer_df = auto_df
            answer_text = "**Automation candidates ranked by fit:**"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "category", "y_col": "potential_saving", "y_title": "Potential Saving (£)", "color_col": "automation_fit"}

        elif any(w in q for w in ["recommend", "top 3", "what should", "action", "suggest"]):
            answer_text = ("**Top 3 Recommendations:**\n\n"
                           "1. 🔄 **Redeploy underutilised staff** — Nadia Kowalski (40%) and Ingrid Johansson (60%) "
                           "to IT Service Desk, Finance Ops, or Commercial (all CRITICAL).\n\n"
                           "2. 🤖 **Automate access requests** — 14 tickets, stddev 0.9d, 86% low priority. "
                           "Self-service portal frees IT capacity.\n\n"
                           "3. 🛡️ **Cross-train HR & Commercial** — only 3 people each, "
                           "33% capacity loss per absence, both have open high-priority tickets.")

        elif any(w in q for w in ["resolution", "how long", "resolve", "turnaround"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
                    WHERE tk.status = 'resolved' AND tk.resolved_date IS NOT NULL
                    WITH t.name AS team, tk.category AS category,
                         duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days
                    RETURN team, category,
                           round(avg(days), 1) AS avg_days,
                           min(days) AS min_days,
                           max(days) AS max_days,
                           count(*) AS tickets
                    ORDER BY avg_days DESC
                """)
            else:
                answer_df = mock_data.get_resolution_time(team_filter)
            answer_text = "**Average resolution time by team and category:**"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "category", "y_col": "avg_days", "y_title": "Avg Days", "color_col": "team"}

        elif any(w in q for w in ["longest", "slowest", "category take"]):
            if USE_NEO4J:
                answer_df = run_query("""
                    MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
                    WHERE tk.status = 'resolved' AND tk.resolved_date IS NOT NULL
                    WITH tk.category AS category,
                         duration.between(date(tk.created_date), date(tk.resolved_date)).days AS days
                    RETURN category, count(*) AS tickets,
                           round(avg(days), 1) AS avg_days,
                           min(days) AS min_days, max(days) AS max_days
                    ORDER BY avg_days DESC
                """)
            else:
                answer_df = mock_data.get_resolution_variance(team_filter)
            answer_text = "**Categories ranked by average resolution time:**"
            chart_type = "bar_v"
            chart_kwargs = {"x_col": "category", "y_col": "avg_days", "y_title": "Avg Days"}

        elif "who is on" in q or "project" in q:
            # Try to extract project name
            if USE_NEO4J:
                projects = run_query("MATCH (p:Project) RETURN p.name AS name")
            else:
                projects = mock_data.get_project_effort(team_filter)[["project"]].rename(columns={"project": "name"})
            matched = None
            for _, p in projects.iterrows():
                if p["name"].lower() in q:
                    matched = p["name"]
                    break
            if matched:
                if USE_NEO4J:
                    answer_df = run_query("""
                        MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project {name: $project}),
                              (e)-[:MEMBER_OF]->(t:Team)
                        RETURN e.name AS name, e.role AS role, t.name AS team,
                               a.percentage AS allocation
                        ORDER BY a.percentage DESC
                    """, {"project": matched})
                else:
                    answer_df = mock_data.get_project_detail(matched, team_filter)
                answer_text = f"**People on {matched}:**"
                chart_type = "bar_h"
                chart_kwargs = {"x_col": "allocation", "y_col": "name", "x_title": "Allocation %"}
            else:
                if USE_NEO4J:
                    answer_df = run_query("""
                        MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
                        WITH p.name AS project, count(DISTINCT e) AS people,
                             sum(a.percentage) AS total_effort
                        RETURN project, people, total_effort
                        ORDER BY total_effort DESC
                    """)
                else:
                    answer_df = mock_data.get_project_effort(team_filter)
                answer_text = "**All projects by effort:**"
                chart_type = "bar_v"
                chart_kwargs = {"x_col": "project", "y_col": "total_effort", "y_title": "Total Effort %"}

        else:
            answer_text = ("I can answer questions about:\n"
                           "- **People**: overloaded, spare capacity, skills, fragility\n"
                           "- **Tickets**: open tickets, resolution times, slowest categories\n"
                           "- **Costs**: total cost, project costs, budget\n"
                           "- **Projects**: who's on what, project effort\n"
                           "- **Recommendations**: top 3, automation candidates\n\n"
                           "Try asking something like *'Who is overloaded?'* or *'Which teams are under pressure?'*")

        # Store answer and rerun to display in chat_container
        response = {"role": "assistant", "text": answer_text, "df": answer_df,
                    "chart_type": chart_type, "chart_kwargs": chart_kwargs}
        st.session_state.chat_history.append(response)
        st.rerun()
