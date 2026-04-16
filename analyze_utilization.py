import json

with open('data/workforce.json') as f:
    workforce = json.load(f)

# Group by role
role_data = {}
for e in workforce:
    role = e['role']
    if role not in role_data:
        role_data[role] = {'count': 0, 'total_allocation': 0}
    role_data[role]['count'] += 1
    role_data[role]['total_allocation'] += e.get('total_allocation', 0)

print("Resource Utilisation Analysis (Target: 80% per resource)\n")
print(f"{'Role':<40} {'Current':<10} {'Avg %':<10} {'Resources':<15}")
print(f"{'':40} {'Count':<10} {'Util':<10} {'to reach 80%':<15}")
print("=" * 80)

total_current = 0
total_required = 0

for role in sorted(role_data.keys()):
    data = role_data[role]
    count = data['count']
    total_alloc = data['total_allocation']
    avg_util = (total_alloc / count) if count > 0 else 0
    
    # To reach 80% utilization: need resources = total_allocation / 80
    resources_needed = total_alloc / 80
    additional = resources_needed - count
    
    total_current += count
    total_required += resources_needed
    
    print(f"{role:<40} {count:<10} {avg_util:>6.1f}%    {resources_needed:>10.2f}")

print("=" * 80)
total_alloc_sum = sum(d['total_allocation'] for d in role_data.values())
avg_overall = (total_alloc_sum / total_current) if total_current > 0 else 0
print(f"{'TOTAL':<40} {total_current:<10} {avg_overall:>6.1f}%    {total_required:>10.2f}")
print(f"\nAdditional resources needed to reach 80% utilization: {total_required - total_current:.2f}")
print(f"New total headcount would be: {int(total_required)}")
