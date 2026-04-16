// ============================================================
// SCHEMA EXPLORATION
// ============================================================

// 1. All node types and counts
MATCH (n)
WITH labels(n)[0] AS label, count(n) AS count
RETURN label, count ORDER BY count DESC;

// 2. All relationship types with source → target
MATCH (a)-[r]->(b)
WITH labels(a)[0] AS from, type(r) AS rel, labels(b)[0] AS to, count(*) AS count
RETURN from, rel, to, count ORDER BY count DESC;

// 3. Full org hierarchy — who reports to whom
MATCH (e:Employee)-[:REPORTS_TO]->(mgr:Employee)
RETURN mgr.name AS manager, mgr.role AS manager_role,
       collect(e.name) AS direct_reports, count(e) AS report_count
ORDER BY report_count DESC;


// ============================================================
// CAPACITY & WORKLOAD
// ============================================================

// 4. Overloaded staff (allocation > 100%)
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
WHERE e.total_allocation > 100
RETURN e.name, e.role, t.name AS team, e.total_allocation AS allocation_pct
ORDER BY e.total_allocation DESC;

// 5. Underutilised staff with spare capacity
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
WHERE e.total_allocation < 80
RETURN e.name, e.role, t.name AS team, e.total_allocation AS allocation_pct,
       (100 - e.total_allocation) AS spare_capacity
ORDER BY spare_capacity DESC;

// 6. Team capacity overview
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
WITH t.name AS team,
     count(e) AS headcount,
     round(avg(e.total_allocation), 0) AS avg_allocation,
     max(e.total_allocation) AS max_allocation,
     min(e.total_allocation) AS min_allocation,
     sum(CASE WHEN e.total_allocation > 100 THEN 1 ELSE 0 END) AS overloaded_count
RETURN team, headcount, avg_allocation, min_allocation, max_allocation, overloaded_count
ORDER BY avg_allocation DESC;


// ============================================================
// TICKET / DEMAND ANALYSIS
// ============================================================

// 7. Open tickets by team and priority (current backlog)
MATCH (tk:Ticket {status: 'open'})-[:ASSIGNED_TO]->(t:Team)
RETURN t.name AS team, tk.priority, tk.ticket_id, tk.description
ORDER BY t.name,
         CASE tk.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END;

// 8. Ticket volume per team with tickets-per-person ratio
MATCH (tk:Ticket)-[:ASSIGNED_TO]->(t:Team)
WITH t.name AS team,
     count(tk) AS total_tickets,
     sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS open_tickets,
     sum(CASE WHEN tk.status = 'resolved' THEN 1 ELSE 0 END) AS resolved_tickets
MATCH (e:Employee)-[:MEMBER_OF]->(t2:Team {name: team})
WITH team, total_tickets, open_tickets, resolved_tickets, count(e) AS headcount
RETURN team, headcount, total_tickets, open_tickets, resolved_tickets,
       round(toFloat(total_tickets) / headcount, 1) AS tickets_per_person
ORDER BY tickets_per_person DESC;

// 9. Tickets by category — what type of demand is coming in
MATCH (tk:Ticket)
RETURN tk.category AS category, count(tk) AS total,
       sum(CASE WHEN tk.status = 'open' THEN 1 ELSE 0 END) AS still_open
ORDER BY total DESC;

// 10. High priority open tickets — director's attention list
MATCH (tk:Ticket {status: 'open', priority: 'high'})-[:ASSIGNED_TO]->(t:Team)
RETURN tk.ticket_id, t.name AS team, tk.category, tk.created_date, tk.description
ORDER BY tk.created_date;


// ============================================================
// SKILLS & RISK
// ============================================================

// 11. Single points of failure — skills held by only one person
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
WITH s.name AS skill, collect(e.name) AS people, count(e) AS holder_count
WHERE holder_count = 1
RETURN skill, people[0] AS sole_holder
ORDER BY skill;

// 12. Find people with a specific skill (e.g. Python) sorted by availability
MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill {name: 'Python'}),
      (e)-[:MEMBER_OF]->(t:Team)
RETURN e.name, e.role, t.name AS team, e.total_allocation AS current_load
ORDER BY e.total_allocation ASC;

// 13. Skills coverage per team
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team), (e)-[:HAS_SKILL]->(s:Skill)
WITH t.name AS team, s.name AS skill, count(e) AS people_with_skill
RETURN team, skill, people_with_skill
ORDER BY team, people_with_skill DESC;


// ============================================================
// PROJECT STAFFING
// ============================================================

// 14. Project staffing and total effort
MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project)
WITH p.name AS project,
     collect({name: e.name, pct: a.percentage}) AS staff,
     sum(a.percentage) AS total_effort,
     count(e) AS people
RETURN project, people, total_effort, staff
ORDER BY total_effort DESC;

// 15. Cross-team project dependencies — projects with staff from multiple teams
MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
WITH p.name AS project, collect(DISTINCT t.name) AS teams, count(DISTINCT t) AS team_count
WHERE team_count > 1
RETURN project, team_count, teams
ORDER BY team_count DESC;

// 16. Employee workload breakdown — what is each person spending time on
MATCH (e:Employee)-[a:ALLOCATED_TO]->(p:Project), (e)-[:MEMBER_OF]->(t:Team)
RETURN e.name, t.name AS team, e.total_allocation,
       collect({project: p.name, pct: a.percentage}) AS projects
ORDER BY e.total_allocation DESC;


// ============================================================
// LOCATION & DISTRIBUTION
// ============================================================

// 17. Staff distribution by location
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
RETURN e.location AS location, count(e) AS headcount,
       collect(DISTINCT t.name) AS teams_present
ORDER BY headcount DESC;

// 18. Grade distribution per team
MATCH (e:Employee)-[:MEMBER_OF]->(t:Team)
RETURN t.name AS team, e.grade, count(e) AS count
ORDER BY t.name, e.grade;
