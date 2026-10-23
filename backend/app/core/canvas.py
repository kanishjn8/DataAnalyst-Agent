"""Canvas dependency helpers. Data preparation is executed by DuckDB."""


def inputs(operation):
    return (
        operation["fileIds"]
        if operation["kind"] == "stack"
        else [operation["leftId"], operation["rightId"]]
    )


def prune(graph, removed):
    removed = set(removed)
    while True:
        extra = {
            node["id"] for node in graph["operations"] if set(inputs(node["operation"])) & removed
        }
        if extra <= removed:
            break
        removed |= extra
    return {
        **graph,
        "operations": [node for node in graph["operations"] if node["id"] not in removed],
        "positions": {
            key: value for key, value in graph["positions"].items() if key not in removed
        },
    }
