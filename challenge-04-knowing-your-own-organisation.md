# Challenge 4: Knowing your own organisation

A minister asks a director a question: how many of your people are working on the new priority programme, and do you have the capacity to absorb more? The director does not know the answer. They send an email to four team leaders. Two respond by end of day. One sends a spreadsheet that uses different categories to another. The director pieces together an approximate answer and sends it back two days later.

This is not unusual. Departments hold significant information about their people, their projects, and their operational workload — but it is distributed across systems that were not designed to work together, and it is rarely accessible in a form that allows leaders to act on it quickly.

## The experience today

A head of operations needs to understand where her teams are under pressure before a quarterly review. She knows IT support tickets have been rising, but she does not know which teams are handling the most volume or which categories are taking the longest to resolve. She asks the IT service desk manager, who sends her a spreadsheet exported from the ticketing system. She has to manipulate it to get the view she needs. It takes an afternoon.

She also wants to know whether she has capacity to move two people onto a new project without destabilising existing commitments. She has a rough idea from memory, but she is not certain. The HR system shows headcount but not project allocation. The project tracker shows allocations but does not link to the HR system. The answer is spread across both, and neither is up to date.

At the same time, a team leader is trying to make the case to his director for more resource. He knows his team is at capacity, but he cannot easily show it in a way that will be convincing. His evidence is qualitative — his team tells him they are busy. He does not have data to support the conversation.

## The users

**The director or senior leader** — needs to answer questions from ministers, permanent secretaries, and senior officials. They need a clear, reliable picture of their organisation — not a spreadsheet they have to interpret. When a new priority emerges, they need to know quickly whether they have the capacity to respond.

**The head of operations or resource manager** — responsible for workforce allocation and operational workload across multiple teams. They need to identify pressure points before they become crises, and to make decisions about redeployment and prioritisation based on evidence rather than instinct.

**The team leader** — wants to demonstrate the workload and capacity of their team, make the case for resource when needed, and understand where their team is carrying risk due to single points of dependency.

**The operational team member** — processing high volumes of requests, many of which follow identical or near-identical patterns. They know which processes are repetitive and which take far longer than they should, but that knowledge rarely surfaces in a form that anyone can act on.

## Why this matters

Resource allocation in government is rarely visible in one place. Senior leaders making staffing decisions often do not have a complete picture. Teams can be under-resourced on critical projects while others have capacity that is not easily visible across the organisation. When a new priority emerges, identifying who could be redeployed without disrupting existing work typically requires a significant amount of manual effort.

This is not a data science problem. The data usually exists somewhere. The problem is that no one has joined it up and made it accessible to the people who need it. A tool that gives a director a clear, reliable answer to even one important question would be more useful than what most departments have today.

## Data provided

A starter dataset is available in the hackathon repository at `challenge-4/`:

| File | Description |
|------|-------------|
| `workforce.json` | 25 synthetic employee records across 6 teams, with roles, grades, skills, and project allocations — including deliberate patterns of over-allocation, under-allocation, and skills concentration |
| `tickets.json` | 50 synthetic operational tickets across IT, Finance, HR, and Commercial, with categories, priorities, assigned teams, and resolution dates |
| `org-chart.json` | Organisation structure for a fictional corporate services directorate with 6 teams and reporting lines |

The starter data is enough to build and demo against. You will find patterns worth exploring — look for them before you start building. If you need more records, use your AI coding tool to generate them using the same schema. See Hint 3 for a generation prompt.

### Sample workforce record structure

Each record in `workforce.json` follows this structure:

```json
{
  "employee_id": "EMP-0042",
  "name": "Priya Sharma",
  "grade": "SEO",
  "role": "Software Developer",
  "team": "Digital Services",
  "team_lead": "EMP-0012",
  "skills": ["Python", "React", "AWS", "data engineering"],
  "allocations": [
    {
      "project": "Benefits Platform Rebuild",
      "percentage": 60
    },
    {
      "project": "Data Migration Phase 2",
      "percentage": 30
    }
  ],
  "total_allocation": 90,
  "location": "Manchester",
  "start_date": "2023-06-15"
}
```

### Sample ticket record structure

```json
{
  "ticket_id": "TKT-2026-01542",
  "category": "access_request",
  "priority": "medium",
  "assigned_team": "IT Service Desk",
  "created_date": "2026-02-14",
  "resolved_date": "2026-02-18",
  "status": "resolved",
  "description": "New starter requires access to SharePoint, Jira, and the HR portal."
}
```

### Sample org chart structure

```json
{
  "team": "Digital Services",
  "team_lead": "EMP-0012",
  "parent_team": "Technology Directorate",
  "headcount": 14,
  "members": ["EMP-0042", "EMP-0043", "EMP-0044"]
}
```

---

<details>
<summary><strong>Hint 1 — Explore the problem: what does a director actually need to know?</strong></summary>

Before writing any code, open the data files and look at them. Then use your AI coding tool to understand what questions are worth answering.

```
I am designing a workforce and operational visibility tool for
a government department. What questions would a director or head
of operations most want answered about their people and workload?
What decisions could they make more effectively with reliable
data?
```

```
Here is a sample of workforce allocation data: [paste a few
records from workforce.json]. What patterns might indicate a
problem? What would over-commitment look like? What would a
skills concentration risk look like?
```

```
Here is a sample of support ticket data: [paste a few records
from tickets.json]. What questions could this data answer for
an operations manager? What would long resolution times in a
particular category suggest?
```

</details>

<details>
<summary><strong>Hint 2 — Possible directions and design questions</strong></summary>

Once you understand the questions that matter, you have a choice about where to focus. The data covers two different areas — workforce allocation and operational tickets — and they can be used separately or together.

**The workforce question.** The allocation data can tell you which teams are over-committed, which have capacity, where skills are concentrated in a single person, and whether the right people are on the right projects. Answering any one of these well, clearly, in a format a non-technical director can act on, is a strong outcome.

**The operational question.** The ticket data can tell you which teams are carrying the most operational load, which categories of request take the longest to resolve, and where backlogs are building. This is a different kind of visibility from the workforce data, but it reflects the same underlying challenge: leaders making decisions without a clear picture of where the pressure actually is.

**Joining them up.** The most interesting analysis comes from combining both: which teams are simultaneously over-committed on project work and handling high ticket volumes? Where is operational demand highest relative to available capacity?

**The automation question.** If you look at the ticket data and find patterns — categories of request that appear frequently and follow a predictable process — there is a further question: which of these processes would be good candidates for automation, and why? Making that case from data, rather than instinct, is a harder but more valuable output.

Think carefully about the format. A director needs to read your output in under two minutes. That shapes everything about how you present the data.

</details>

<details>
<summary><strong>Hint 3 — A starting point with specific prompts</strong></summary>

If your team wants a concrete direction, here is one approach.

To generate more records if you need them:

```
Here is the structure of a workforce record: [paste one record
from workforce.json]. Generate 50 more synthetic employee
records across the same 6 teams. Include a realistic mix:
some over-allocated (total above 100%), some under-allocated
(total below 70%), and at least 3 people whose skills appear
in no other team.
```

Start by exploring the data:

```
I have a JSON file of employee records with team, grade, skills,
and project allocations as percentages. Analyse this data and
tell me: how many employees are over-allocated (above 100%),
how many are under-allocated (below 70%), which teams have the
highest average allocation, and which skills appear in only one
team.
```

Then build a clear answer to one question:

```
I have workforce allocation data. Build a simple dashboard that
answers: "Which teams are over-committed?" Show a bar chart of
average allocation by team, highlight teams above 100%, and
list the individuals who are over-allocated and the projects
causing it. Use a simple charting library. Make it readable for
a non-technical audience.
```

If you want to bring in the ticket data:

```
I have support tickets with category, assigned team, created
date, and resolved date. Calculate average resolution time by
team and category. Identify the team-category combinations with
the longest average resolution time and flag any that are still
open.
```

From there: what would a director need to see to decide whether to redeploy resource? What are the top three things you would recommend based on what the data shows?

</details>

## What does a good outcome look like?

By the end of the day, you should be able to show a clear answer to at least one specific question a director would actually ask — presented in a format they could read in under two minutes. If you can also explain what the data reveals, what you would recommend based on it, and what you would need to go further, that is a strong and credible demo.

## Useful references

- Civil Service statistics — https://www.gov.uk/government/collections/civil-service-statistics — published workforce data from the Cabinet Office
- ONS public sector employment — https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/publicsectorpersonnel — national employment statistics

---
Version: 1.1
Last updated: April 2026
