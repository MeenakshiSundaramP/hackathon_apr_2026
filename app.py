import os
import streamlit as st
import pandas as pd
import altair as alt
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# --- Neo4j connection ---
@st.cache_resource
def get_driver():
    return GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD")),
    )

def run_query(query, params=None):
    driver = get_driver()
    with driver.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
        result = session.run(query, params or {})
        return pd.DataFrame([r.data() for r in result])


# --- Page config ---
st.set_page_config(page_title="Workforce Visibility Dashboard", layout="wide", page_icon="🏛️")
st.title("🏛️ Workforce & Operational Visibility")
st.caption("Directorate of Corporate Services — Live from Neo4j")

# --- Sidebar filters ---
st.sidebar.header("Filters")
teams_df = run_query("MATCH (t:Team) RETURN t.name AS team ORDER BY t.name")
all_teams = teams_df["team"].tolist()
selected_teams = st.sidebar.multiselect("Teams", all_teams, default=all_teams)

if not selected_teams:
    st.warning("Select at least one team.")
    st.stop()

team_filter = selected_teams

# --- Tab layout ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Overview", "👥 Capacity", "🎫 Tickets", "🧠 Skills & Risk", "📁 Projects"
])

# ===================== TAB 1: OVERVIEW =====================
with tab1:
    col1, col2, col3, col4 = st.columns(4)

    headcount_df = run_query("""
        MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN count(e) AS headcount
    """, {"teams": team_filter})

    open_tickets_df = run_query("""
        MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team)
        WHERE t.name IN $teams
        RETURN count(tk) AS open_tickets
    """, {"teams": team_filter})

    overloaded_df = run_query("""
        MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams AND e.total_allocation > 100
        RETURN count(e) AS overloaded
    """, {"teams": team_filter})

    avg_alloc_df = run_query("""
        MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN round(avg(e.total_allocation), 0) AS avg_allocation
    """, {"teams": team_filter})

    col1.metric("Headcount", int(headcount_df["headcount"].iloc[0]))
    col2.metric("Open Tickets", int(open_tickets_df["open_tickets"].iloc[0]))
    col3.metric("Overloaded Staff (>100%)", int(overloaded_df["overloaded"].iloc[0]))
    col4.metric("Avg Allocation", f"{int(avg_alloc_df['avg_allocation'].iloc[0])}%")

    st.divider()

    # Org hierarchy
    st.subheader("Reporting Structure")
    hierarchy_df = run_query("""
        MATCH (e:Employee)-[:REPORTS_TO]->(mgr:Employee)
        MATCH (e)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN mgr.name AS manager, mgr.role AS role,
               collect(e.name) AS direct_reports, count(e) AS report_count
        ORDER BY report_count DESC
    """, {"teams": team_filter})
    if not hierarchy_df.empty:
        for _, row in hierarchy_df.iterrows():
            with st.expander(f"**{row['manager']}** — {row['role']} ({row['report_count']} reports)"):
                for name in row["direct_reports"]:
                    st.write(f"  • {name}")

    # Tenure analysis
    st.subheader("Tenure Analysis")
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
    location_df = run_query("""
        MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN e.location AS location, count(e) AS headcount
        ORDER BY headcount DESC
    """, {"teams": team_filter})
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
        over_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams AND e.total_allocation > 100
            RETURN e.name AS name, e.role AS role, t.name AS team,
                   e.total_allocation AS allocation
            ORDER BY e.total_allocation DESC
        """, {"teams": team_filter})
        if not over_df.empty:
            st.dataframe(over_df, use_container_width=True, hide_index=True)
        else:
            st.success("No overloaded staff!")

    with col_under:
        st.subheader("🟢 Available Capacity")
        under_df = run_query("""
            MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams AND e.total_allocation < 80
            RETURN e.name AS name, e.role AS role, t.name AS team,
                   e.total_allocation AS allocation,
                   (100 - e.total_allocation) AS spare_capacity
            ORDER BY spare_capacity DESC
        """, {"teams": team_filter})
        if not under_df.empty:
            st.dataframe(under_df, use_container_width=True, hide_index=True)
        else:
            st.info("Everyone is at or above 80% allocation.")

    st.divider()
    st.subheader("Individual Workload Breakdown")
    workload_df = run_query("""
        MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN e.name AS name, t.name AS team, p.name AS project, a.percentage AS pct
        ORDER BY e.name, a.percentage DESC
    """, {"teams": team_filter})
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
    st.subheader("🚨 Open Tickets — Director's Attention List")
    open_df = run_query("""
        MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team)
        WHERE t.name IN $teams
        RETURN tk.ticket_id AS ticket, t.name AS team, tk.category AS category,
               tk.priority AS priority, tk.created_date AS created, tk.description AS description
        ORDER BY CASE tk.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 tk.created_date
    """, {"teams": team_filter})
    if not open_df.empty:
        def priority_color(val):
            colors = {"high": "background-color: #ffcccc", "medium": "background-color: #fff3cd", "low": "background-color: #d4edda"}
            return colors.get(val, "")
        st.dataframe(open_df.style.map(priority_color, subset=["priority"]), use_container_width=True, hide_index=True)
    else:
        st.success("No open tickets!")

    st.divider()

    col_vol, col_cat = st.columns(2)

    with col_vol:
        st.subheader("Ticket Volume by Team")
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
        cat_df = run_query("""
            MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
            WHERE t.name IN $teams
            RETURN tk.category AS category, count(tk) AS total,
                   sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS open
            ORDER BY total DESC
        """, {"teams": team_filter})
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

    # Backlog trend
    st.subheader("📈 Backlog Trend Over Time")
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
    col_spof, col_search = st.columns(2)

    with col_spof:
        st.subheader("⚠️ Single Points of Failure")
        st.caption("Skills held by only one person in selected teams")
        spof_df = run_query("""
            MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            WITH s.name AS skill, collect(e.name) AS holders, count(e) AS count
            WHERE count = 1
            RETURN skill, holders[0] AS sole_holder
            ORDER BY skill
        """, {"teams": team_filter})
        if not spof_df.empty:
            st.dataframe(spof_df, use_container_width=True, hide_index=True, height=400)
        else:
            st.success("No single points of failure!")

    with col_search:
        st.subheader("🔍 Skill Search")
        skills_df = run_query("""
            MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill), (e)-[:MEMBER_OF]->(t:Team)
            WHERE t.name IN $teams
            RETURN DISTINCT s.name AS skill ORDER BY skill
        """, {"teams": team_filter})
        if not skills_df.empty:
            selected_skill = st.selectbox("Find people with skill:", skills_df["skill"].tolist())
            if selected_skill:
                skill_holders = run_query("""
                    MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill {name: $skill}),
                          (e)-[:MEMBER_OF]->(t:Team)
                    WHERE t.name IN $teams
                    RETURN e.name AS name, e.role AS role, t.name AS team,
                           e.total_allocation AS allocation
                    ORDER BY e.total_allocation ASC
                """, {"skill": selected_skill, "teams": team_filter})
                st.dataframe(skill_holders, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Grade Distribution")
    grade_df = run_query("""
        MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        RETURN t.name AS team, e.grade AS grade, count(e) AS count
        ORDER BY t.name, e.grade
    """, {"teams": team_filter})
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
    proj_df = run_query("""
        MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        WITH p.name AS project, count(DISTINCT e) AS people,
             sum(a.percentage) AS total_effort
        RETURN project, people, total_effort
        ORDER BY total_effort DESC
    """, {"teams": team_filter})
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
    cross_df = run_query("""
        MATCH (e:Employee)-[:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
        WHERE t.name IN $teams
        WITH p.name AS project, collect(DISTINCT t.name) AS teams, count(DISTINCT t) AS team_count
        WHERE team_count > 1
        RETURN project, team_count, teams
        ORDER BY team_count DESC
    """, {"teams": team_filter})
    if not cross_df.empty:
        st.dataframe(cross_df, use_container_width=True, hide_index=True)
    else:
        st.info("No cross-team project dependencies found.")

    st.divider()
    st.subheader("Project Detail")
    if not proj_df.empty:
        selected_project = st.selectbox("Select project:", proj_df["project"].tolist())
        if selected_project:
            detail_df = run_query("""
                MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project {name: $project}),
                      (e)-[:MEMBER_OF]->(t:Team)
                WHERE t.name IN $teams
                RETURN e.name AS name, e.role AS role, t.name AS team,
                       a.percentage AS allocation
                ORDER BY a.percentage DESC
            """, {"project": selected_project, "teams": team_filter})
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
