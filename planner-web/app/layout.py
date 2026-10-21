"""Overlap column layout, ported from the Swift app's TaskLayoutEngine
(standard interval-graph-coloring technique for calendar day views)."""

from dataclasses import dataclass

from .models import Task


@dataclass
class TaskLayout:
    task: Task
    column: int
    column_count: int


def layout_tasks(tasks: list[Task]) -> list[TaskLayout]:
    sorted_tasks = sorted(tasks, key=lambda t: (t.start_minutes, t.duration_minutes))

    clusters: list[list[Task]] = []
    current_cluster: list[Task] = []
    cluster_end = -1

    for task in sorted_tasks:
        if not current_cluster or task.start_minutes < cluster_end:
            current_cluster.append(task)
            cluster_end = max(cluster_end, task.end_minutes)
        else:
            clusters.append(current_cluster)
            current_cluster = [task]
            cluster_end = task.end_minutes
    if current_cluster:
        clusters.append(current_cluster)

    result: list[TaskLayout] = []
    for cluster in clusters:
        column_end_times: list[int] = []
        assignments: list[tuple[Task, int]] = []
        for task in cluster:
            placed = False
            for idx, end_time in enumerate(column_end_times):
                if task.start_minutes >= end_time:
                    column_end_times[idx] = task.end_minutes
                    assignments.append((task, idx))
                    placed = True
                    break
            if not placed:
                column_end_times.append(task.end_minutes)
                assignments.append((task, len(column_end_times) - 1))

        column_count = len(column_end_times)
        for task, col in assignments:
            result.append(TaskLayout(task=task, column=col, column_count=column_count))

    return result
