// Idempotent data load for challenge-4 JSON files
// Expects files in Neo4j import dir:
// - workforce.json
// - tickets.json
// - org-chart.json

CREATE CONSTRAINT employee_id IF NOT EXISTS
FOR (e:Employee)
REQUIRE e.employee_id IS UNIQUE;

CREATE CONSTRAINT team_name IF NOT EXISTS
FOR (t:Team)
REQUIRE t.name IS UNIQUE;

CREATE CONSTRAINT ticket_id IF NOT EXISTS
FOR (tk:Ticket)
REQUIRE tk.ticket_id IS UNIQUE;

CREATE CONSTRAINT project_name IF NOT EXISTS
FOR (p:Project)
REQUIRE p.name IS UNIQUE;

CREATE CONSTRAINT skill_name IF NOT EXISTS
FOR (s:Skill)
REQUIRE s.name IS UNIQUE;

// Workforce: employees, teams, skills, project allocations
CALL apoc.load.json("file:///workforce.json") YIELD value AS row
MERGE (e:Employee {employee_id: row.employee_id})
SET e.name = row.name,
    e.grade = row.grade,
    e.role = row.role,
    e.total_allocation = row.total_allocation,
    e.location = row.location,
    e.start_date = row.start_date
MERGE (t:Team {name: row.team})
MERGE (e)-[:MEMBER_OF]->(t)
FOREACH (skill IN coalesce(row.skills, []) |
  MERGE (s:Skill {name: skill})
  MERGE (e)-[:HAS_SKILL]->(s)
)
FOREACH (alloc IN coalesce(row.allocations, []) |
  MERGE (p:Project {name: alloc.project})
  MERGE (e)-[a:ALLOCATED_TO]->(p)
  SET a.percentage = alloc.percentage
);

// Reporting lines
CALL apoc.load.json("file:///workforce.json") YIELD value AS row
WITH row
WHERE row.team_lead IS NOT NULL
MATCH (e:Employee {employee_id: row.employee_id})
MATCH (mgr:Employee {employee_id: row.team_lead})
MERGE (e)-[:REPORTS_TO]->(mgr);

// Tickets and ownership
CALL apoc.load.json("file:///tickets.json") YIELD value AS row
MERGE (tk:Ticket {ticket_id: row.ticket_id})
SET tk.category = row.category,
    tk.priority = row.priority,
    tk.created_date = row.created_date,
    tk.resolved_date = row.resolved_date,
    tk.status = row.status,
    tk.description = row.description
MERGE (t:Team {name: row.assigned_team})
MERGE (tk)-[:ASSIGNED_TO]->(t);

// Organisation context
CALL apoc.load.json("file:///org-chart.json") YIELD value
MERGE (o:Organisation {name: value.organisation})
WITH value, o
UNWIND value.teams AS teamRow
MERGE (t:Team {name: teamRow.team})
SET t.headcount = teamRow.headcount,
    t.parent_team = teamRow.parent_team
MERGE (t)-[:PART_OF]->(o)
WITH t, teamRow
UNWIND coalesce(teamRow.members, []) AS memberId
MATCH (e:Employee {employee_id: memberId})
MERGE (e)-[:MEMBER_OF]->(t)
WITH t, teamRow
MATCH (lead:Employee {employee_id: teamRow.team_lead})
MERGE (lead)-[:LEADS]->(t);
