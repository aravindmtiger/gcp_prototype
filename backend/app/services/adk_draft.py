"""Render Agent Canvas graphs as executable Google ADK agents."""

import re
from typing import Any

GATEWAY_MODEL_ID = "agent-gateway"
CODE_EXECUTOR_MODEL_ID = "gemini-2.5-flash"


def identifier(name: str) -> str:
    """A safe Python and ADK name: letters, digits and underscores, not starting with a digit."""
    cleaned = re.sub(r"\W", "_", name)
    return cleaned if not cleaned[:1].isdigit() else f"_{cleaned}"


def _function_name(node_id: str, suffix: str) -> str:
    return identifier(f"{suffix}_{node_id}")


def _tool_setup(
    spec: dict[str, Any], source_configs: dict[str, dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Return tool expressions for an LlmAgent and source helpers used by that tool."""
    tool = spec["tool"]
    config = spec["config"]
    node_id = spec["name"]
    helpers: list[str] = []

    if tool == "web_search":
        return ["google_search"], helpers
    if tool == "knowledge_retriever":
        source = source_configs.get(node_id, {})
        corpus = source.get("rag_corpus")
        if not corpus:
            raise ValueError(f"'{node_id}' is missing its configured Vertex AI RAG corpus")
        return [
            "VertexAiRagRetrieval("
            f"name={_function_name(node_id, 'retrieve_knowledge')!r}, "
            "description='Search the configured knowledge corpus', "
            f"rag_corpora={[corpus]!r})"
        ], helpers
    if tool in {"sql_executor", "nosql_executor", "no_sql_executor"}:
        function = _function_name(node_id, "run_query")
        source = source_configs.get(node_id, {})
        if tool == "sql_executor":
            backend = source.get("backend")
            table_ref = source.get("table_ref")
            if not backend or not table_ref:
                raise ValueError(f"'{node_id}' is missing its structured data source configuration")
            helpers.extend(
                [
                    f"def {function}(query: str) -> str:",
                    '    """Run a read-only query on the configured structured source."""',
                    "    normalized_query = query.strip().rstrip(';')",
                    "    if (",
                    "        not normalized_query.lower().startswith('select ')",
                    "        or ';' in normalized_query",
                    "    ):",
                    "        raise ValueError('Only a single SELECT query is allowed')",
                    "    query = normalized_query",
                    f"    table_ref = {table_ref!r}",
                    f"    backend = {backend!r}",
                    "    if backend == 'bigquery':",
                    "        from google.cloud import bigquery",
                    "        client = bigquery.Client()",
                    "        job = client.query(",
                    "            query,",
                    "            job_config=bigquery.QueryJobConfig(",
                    "                maximum_bytes_billed=1_000_000_000",
                    "            ),",
                    "        )",
                    "        return json.dumps([dict(row) for row in job.result()], default=str)",
                    "    if backend == 'cloud_sql':",
                    "        from sqlalchemy import create_engine, text",
                    "        import os",
                    "        dsn = os.environ.get('CLOUD_SQL_DSN')",
                    "        if not dsn:",
                    "            raise RuntimeError('Set CLOUD_SQL_DSN for this Cloud SQL source')",
                    "        engine = create_engine(dsn)",
                    "        try:",
                    "            with engine.connect() as connection:",
                    "                rows = connection.execute(text(query)).mappings().all()",
                    "                return json.dumps([dict(row) for row in rows], default=str)",
                    "        finally:",
                    "            engine.dispose()",
                    "    raise ValueError(f'Unsupported structured backend: {backend}')",
                ]
            )
            return [function], helpers

        collection = config["firestore_collection"]
        helpers.extend(
            [
                f"def {function}(",
                "    filter_field: str = '', filter_value: str = '', limit: int = 20",
                ") -> str:",
                '    """Query documents from the configured Firestore collection."""',
                "    from google.cloud import firestore",
                "    query = firestore.Client().collection(" + repr(collection) + ")",
                "    if filter_field:",
                "        query = query.where(filter_field, '==', filter_value)",
                "    documents = query.limit(max(1, min(limit, 100))).stream()",
                "    rows = [{'id': doc.id, **doc.to_dict()} for doc in documents]",
                "    return json.dumps(rows, default=str)",
            ]
        )
        return [function], helpers
    if tool == "email_sender":
        function = _function_name(node_id, "send_email")
        sender = config["sender_email"]
        helpers.extend(
            [
                f"def {function}(to: str, subject: str, body: str) -> str:",
                '    """Send email through the Gmail API using delegated runtime credentials."""',
                "    import base64",
                "    import email.message",
                "    import google.auth",
                "    from google.auth.transport.requests import AuthorizedSession",
                "    credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/gmail.send'])",
                f"    sender = {sender!r}",
                "    if hasattr(credentials, 'with_subject'):",
                "        credentials = credentials.with_subject(sender)",
                "    message = email.message.EmailMessage()",
                "    message['To'] = to",
                "    message['From'] = sender",
                "    message['Subject'] = subject",
                "    message.set_content(body)",
                "    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip('=')",
                "    response = AuthorizedSession(credentials).post(",
                "        'https://gmail.googleapis.com/gmail/v1/users/me/messages/send',",
                "        json={'raw': raw},",
                "        timeout=30,",
                "    )",
                "    response.raise_for_status()",
                "    return 'Email sent'",
            ]
        )
        return [function], helpers
    if tool == "file_reader":
        function = _function_name(node_id, "read_file")
        bucket = config["gcs_bucket"]
        prefix = config.get("prefix", "")
        helpers.extend(
            [
                f"def {function}(object_name: str) -> str:",
                '    """Read a UTF-8 text object from the configured Cloud Storage bucket."""',
                "    from google.cloud import storage",
                f"    prefix = {prefix!r}",
                "    if prefix and not object_name.startswith(prefix):",
                "        raise ValueError('The object is outside the configured bucket prefix')",
                f"    blob = storage.Client().bucket({bucket!r}).blob(object_name)",
                "    data = blob.download_as_bytes()",
                "    if len(data) > 2_000_000:",
                "        raise ValueError('Files larger than 2 MB are not supported')",
                "    return data.decode('utf-8')",
            ]
        )
        return [function], helpers
    if tool == "mcp_server":
        return [], helpers
    return [], helpers


def _instruction(spec: dict[str, Any]) -> str:
    instruction = spec["instruction"]
    routes = spec.get("routes", [])
    tool = spec["tool"]
    if tool == "router":
        guidance = (
            f"Choose exactly one path from {routes!r}. "
            "Return only the exact path label, without explanation."
        )
        if spec["config"].get("route_instruction"):
            guidance += f" Routing criteria: {spec['config']['route_instruction']}"
        return f"{instruction}\n\n{guidance}".strip()
    if tool == "if_else":
        return (
            f"{instruction}\n\nEvaluate this condition: {spec['config']['condition']}. "
            "Return only 'true' or 'false'."
        ).strip()
    if tool == "loop":
        condition = spec["config"].get("stop_condition") or "the task is complete"
        return (
            f"{instruction}\n\nContinue the loop only while needed to satisfy this stop "
            f"condition: {condition}. Return only 'continue' or 'exit'."
        ).strip()
    return instruction


def _render_agent(
    spec: dict[str, Any],
    source_configs: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str]]:
    variable = identifier(spec["name"])
    tool_expressions, helper_lines = _tool_setup(spec, source_configs)
    model = "CODE_EXECUTOR_MODEL_ID" if spec["tool"] == "code_executor" else "GATEWAY_MODEL_ID"
    lines = [
        f"{variable} = LlmAgent(",
        f"    name={variable!r},",
        f"    model={model},",
        f"    instruction={_instruction(spec)!r},",
        f"    output_key={spec['output_key']!r},",
        "    tools=[",
        *(f"        {expression}," for expression in tool_expressions),
        "    ],",
    ]
    if spec["tool"] == "code_executor":
        lines.append("    code_executor=BuiltInCodeExecutor(),")
    lines.append(")")

    if spec["tool"] in {"router", "if_else", "loop"}:
        function = _function_name(spec["name"], "choose_route")
        selector = identifier(spec["selector"])
        routes = spec["routes"]
        lines.extend(
            [
                f"def {function}(ctx):",
                f"    route = _match_route(ctx.state.get({spec['output_key']!r}, ''), {routes!r})",
            ]
        )
        if spec["tool"] == "loop":
            max_iterations = spec["config"].get("max_iterations", 3)
            lines.extend(
                [
                    f"    count_key = 'loop_count:' + ctx.invocation_id + ':' + {spec['name']!r}",
                    "    count = int(ctx.state.get(count_key, 0)) + 1",
                    "    ctx.state[count_key] = count",
                    f"    if count > {max_iterations}:",
                    "        route = 'exit'",
                ]
            )
        lines.append("    return Event(output={'route': route}, actions=EventActions(route=route))")
        lines.extend(
            [
                f"{selector} = FunctionNode(func={function}, name={selector!r})",
            ]
        )
    return lines, helper_lines


def render_adk_agent(
    name: str,
    description: str,
    graph: dict[str, Any],
    source_configs: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Generate an ADK Workflow with executable tools, routed branches, and resumable HITL."""
    source_configs = source_configs or {}
    imports = {
        "import json",
        "from google.adk.agents import LlmAgent",
        "from google.adk.events import Event",
        "from google.adk.events.event_actions import EventActions",
        "from google.adk.events.request_input import RequestInput",
        "from google.adk.workflow import Edge, FunctionNode, START, Workflow",
    }
    if any(
        node["tool"] == "web_search" for node in graph["root"]["nodes"] if node["type"] == "agent"
    ):
        imports.add("from google.adk.tools import google_search")
    if any(
        node["tool"] == "knowledge_retriever"
        for node in graph["root"]["nodes"]
        if node["type"] == "agent"
    ):
        imports.add(
            "from google.adk.tools.retrieval.vertex_ai_rag_retrieval import VertexAiRagRetrieval"
        )
    if any(
        node["tool"] == "code_executor"
        for node in graph["root"]["nodes"]
        if node["type"] == "agent"
    ):
        imports.add("from google.adk.code_executors import BuiltInCodeExecutor")

    body: list[str] = []
    node_variables: dict[str, str] = {}
    for spec in graph["root"]["nodes"]:
        variable = identifier(spec["name"])
        node_variables[spec["name"]] = variable
        if spec["type"] == "agent":
            lines, helpers = _render_agent(spec, source_configs)
            body.extend(helpers)
            if helpers:
                body.append("")
            body.extend(lines)
            if "selector" in spec:
                node_variables[spec["name"]] = variable
                node_variables[spec["selector"]] = identifier(spec["selector"])
        elif spec["type"] == "hitl":
            options = spec["routes"]
            function = _function_name(spec["name"], "request_choice")
            message = spec["config"].get("message", "Choose how to continue.")
            body.extend(
                [
                    f"def {function}(ctx):",
                    f"    interrupt_id = 'hitl:' + {spec['name']!r}",
                    "    choice = ctx.resume_inputs.get(interrupt_id)",
                    "    if choice is None:",
                    "        yield RequestInput(",
                    "            interrupt_id=interrupt_id,",
                    f"            message={message!r},",
                    f"            payload={{'choices': {options!r}}},",
                    "            response_schema={",
                    "                'type': 'object',",
                    "                'properties': {",
                    f"                    'choice': {{'type': 'string', 'enum': {options!r}}},",
                    "                },",
                    "                'required': ['choice'],",
                    "            },",
                    "        )",
                    "        return",
                    "    if isinstance(choice, dict):",
                    "        choice = choice.get('choice')",
                    f"    route = _match_route(choice, {options!r})",
                    "    return Event(output={'route': route}, actions=EventActions(route=route))",
                    f"{variable} = FunctionNode(",
                    f"    func={function}, name={variable!r}, rerun_on_resume=True",
                    ")",
                    "",
                ]
            )
        elif spec["type"] == "terminal":
            body.append(f"{variable} = FunctionNode(func=lambda: None, name={variable!r})")

    helper = [
        "def _match_route(value, allowed):",
        "    if isinstance(value, dict):",
        "        value = value.get('route', value.get('choice', value.get('output', '')))",
        "    text = str(value).strip()",
        "    try:",
        "        parsed = json.loads(text)",
        "    except (TypeError, ValueError):",
        "        parsed = None",
        "    if isinstance(parsed, dict):",
        "        text = str(parsed.get('route', parsed.get('choice', text))).strip()",
        "    for option in allowed:",
        "        if text.casefold() == option.casefold():",
        "            return option",
        "    raise ValueError(f'Expected one of {allowed!r}, received {text!r}')",
        "",
    ]
    edges = [
        f"    Edge(from_node=START, to_node={node_variables[node_id]}),"
        for node_id in graph["root"]["entry_nodes"]
    ]
    for edge in graph["root"]["edges"]:
        route = f", route={edge['route']!r}" if edge["route"] is not None else ""
        edges.append(
            f"    Edge(from_node={node_variables[edge['source']]}, "
            f"to_node={node_variables[edge['target']]}{route}),"
        )
    workflow = [
        "root_agent = Workflow(",
        f"    name={identifier(name)!r},",
        f"    description={description!r},",
        "    edges=[",
        *edges,
        "    ],",
        ")",
    ]
    lines = [
        '"""Generated from the Agent Canvas. Edit the canvas, not this file."""',
        "",
        *sorted(imports),
        "",
        f"GATEWAY_MODEL_ID = {GATEWAY_MODEL_ID!r}",
        "CODE_EXECUTOR_MODEL_ID = __import__('os').environ.get(",
        f"    'ADK_CODE_EXECUTOR_MODEL', {CODE_EXECUTOR_MODEL_ID!r}",
        ")",
        "",
        *helper,
        *body,
        "",
        *workflow,
        "",
    ]
    return "\n".join(lines)
