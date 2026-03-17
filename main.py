"""
Consciousness-First Dual-Pass Agent Architecture — Main Orchestrator
  Layer 1: Dreamer (Consciousness) → free text, temp=0.7
  Layer 2: Executor (Translator) → JSON, temp=0.1
  Layer 3: Python Orchestrator → security, execution, synchronization
"""
import sys
import re
from pathlib import Path

from core.llm import consciousness_call, action_intent_call, executor_call, is_alive
from core.memory import Memory, EntityTracker, trim_history
from tools.bash import bash
from tools.read_file_tool import read_file
from tools.write_file_tool import write_file
from tools.memory_tools import append_to_memory, update_section, read_section, edit_line, delete_line
from tools.app_launcher import (
    open_app, open_app_workspace, youtube_search_play, switch_workspace,
    read_active_workspace, list_open_windows, move_window_workspace, vscode_open_project,
)
from tools.tavily_tools import web_research, read_page

from tools.tavily_tools import web_research, read_page
from core.audio_handler import speak, listen

from config import BASE_MAX_LOOPS, EXTENDED_MAX_LOOPS, ASSISTANT_NAME, USER_NAME
from prompts import SYSTEM_GREETING


def load_system() -> str:
    """Loads SOUL.md + USER.md as the system prompt."""
    base_dir = Path(__file__).parent
    parts = []

    for fname in ["SOUL.md", "SKILL.md", "USER.md"]:
        p = base_dir / fname
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
            print(f"[SYSTEM] {fname} loaded successfully! (Length: {len(parts[-1])} characters)")
        else:
            print(f"[WARNING] {fname} not found! Searched at: {p}")

    return "\n\n---\n\n".join(parts)


def _extract_requested_workspace(text: str) -> str | None:
    t = text.lower()
    patterns = [
        r"workspace\s*(\d+)",
        r"(\d+)\s*\.?\s*workspace",
    ]
    for p in patterns:
        m = re.search(p, t)
        if not m:
            continue
        raw = m.group(1)
        if not raw.isdigit():
            continue
        n = int(raw)
        if n == 0:
            return "10"
        if 1 <= n <= 10:
            return str(n)
    return None



def execute_tool(action: dict) -> str:
    """
    Executes JSON command from Executor through security filter.
    Returns result as plain text.
    """
    action_name = action.get("action", "none")

    try:
        if action_name == "bash":
            command = action.get("command", "")
            print(f"  └─> Command: {command}")
            return bash(command)

        elif action_name == "read_file":
            file = action.get("file", "")
            print(f"  └─> File: {file}")
            return read_file(file)

        elif action_name == "write_file":
            file = action.get("file", "")
            content = action.get("content", "")
            print(f"  └─> File: {file}")
            return write_file(file, content)

        elif action_name == "memory_append":
            file = action.get("file", "")
            section = action.get("section", "")
            content = action.get("content", "")
            print(f"  └─> File: {file} | Section: {section}")
            return append_to_memory(file, section, content)

        elif action_name == "memory_update":
            file = action.get("file", "")
            section = action.get("section", "")
            new_content = action.get("new_content", "")
            print(f"  └─> File: {file} | Section: {section}")
            return update_section(file, section, new_content)

        elif action_name == "memory_read":
            file = action.get("file", "")
            section = action.get("section", "")
            print(f"  └─> File: {file} | Section to read: {section}")
            return read_section(file, section)

        elif action_name == "memory_edit":
            file = action.get("file", "")
            section = action.get("section", "")
            old_text = action.get("old", "")
            new_text = action.get("new", "")
            print(f"  └─> File: {file} | Section: {section} | '{old_text}' → '{new_text}'")
            return edit_line(file, section, old_text, new_text)

        elif action_name == "memory_delete":
            file = action.get("file", "")
            section = action.get("section", "")
            text_to_delete = action.get("to_delete", "")
            print(f"  └─> File: {file} | Section: {section} | To delete: '{text_to_delete}'")
            return delete_line(file, section, text_to_delete)

        elif action_name == "open_app":
            app = action.get("app", "")
            print(f"  └─> Application: {app}")
            return open_app(app)

        elif action_name == "vscode_open_project":
            project_path = action.get("project_path", "")
            print(f"  └─> VS Code Open Project: {project_path}")
            return vscode_open_project(project_path)

        elif action_name == "switch_workspace":
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Workspace Switch: {workspace_no}")
            return switch_workspace(workspace_no)

        elif action_name == "open_app_workspace":
            app = action.get("app", "")
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Open App in Workspace: {app} @ {workspace_no}")
            return open_app_workspace(app, workspace_no)

        elif action_name == "read_active_workspace":
            print("  └─> Read Active Workspace")
            return read_active_workspace()

        elif action_name == "list_open_windows":
            print("  └─> List Open Windows")
            return list_open_windows()

        elif action_name == "move_window_workspace":
            window = action.get("window", "")
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Move Window: {window} -> Workspace {workspace_no}")
            return move_window_workspace(window, workspace_no)

        elif action_name == "youtube_search_play":
            search_query = action.get("search_query", "")
            print(f"  └─> YouTube Search: {search_query}")
            return youtube_search_play(search_query)

        elif action_name == "web_research":
            query = action.get("query", "")
            depth = action.get("depth", "advanced")
            print(f"  └─> Web Research: {query} | Depth: {depth}")
            return web_research(query, depth)

        elif action_name == "read_page":
            url = action.get("url", "")
            print(f"  └─> Read Page: {url}")
            return read_page(url)

        elif action_name == "deep_research":
            query = action.get("query", "")
            print(f"  └─> Deep Research: {query}")
            from tools.tavily_tools import deep_research
            return deep_research(query)

        elif action_name == "crawl_page":
            url = action.get("url", "")
            print(f"  └─> Crawl Page: {url}")
            from tools.tavily_tools import crawl_page
            return crawl_page(url)

        else:
            return f"❌ Invalid action: {action_name}"

    except Exception as e:
        return f"❌ Tool execution error: {type(e).__name__}: {e}"


SYSTEM = load_system()



def main():
    if not is_alive():
        print("❌ Ollama is not running. Start: ollama serve")
        sys.exit(1)

    print(f"{SYSTEM_GREETING}")
    print('   Type "exit" to quit\n')

    memory = Memory()
    tracker = EntityTracker()
    history = []

    while True:

        # Either read from mic or input()
        use_mic = False
        try:
            raw_input = input(f"{USER_NAME} (Type text, or type 'mic' to use microphone): ").strip()
            if raw_input.lower() == 'mic':
                use_mic = True
                user = listen()
                if not user:
                    print("Could not hear you. Please type or try again.")
                    continue
            else:
                user = raw_input
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user:
            continue
        if user.lower() in ("exit", "q"):
            print("Goodbye.")
            break

        past = memory.recall(user)
        system = SYSTEM
        if past:
            system += f"\n\n<past_memory>\nThe following is past context recalled from memory:\n{past}\n</past_memory>"

        history.append({"role": "user", "content": user})
        print()

        max_loops = BASE_MAX_LOOPS
        error_count = 0
        loop = 0
        executed_actions = set() 

        while loop < max_loops:
            step_label = f"{'='*20} [Loop {loop+1}/{max_loops}] {'='*20}"
            print(f"\n{step_label}")

            consciousness = consciousness_call(history, system=system)

            has_action_intent = action_intent_call(user, consciousness)

            if not has_action_intent:
                print(f"\n[Executor] Action: none (no action intent detected)")
                history.append({"role": "assistant", "content": consciousness})
                saved = memory.save(user, consciousness)
                if saved:
                    print("[Saved to memory]")
                print()
                if use_mic:
                    speak(consciousness)
                break

            entity_context = tracker.get_context()
            actions = executor_call(
                user,
                consciousness,
                entity_context,
                allow_regex_fallback=(loop == 0),
            )

            requested_workspace = _extract_requested_workspace(user)
            if requested_workspace:
                guarded_actions = []
                for a in actions:
                    action = a.get("action", "none")
                    guarded = dict(a)

                    if action == "open_app":
                        guarded["action"] = "open_app_workspace"
                        guarded["workspace_no"] = requested_workspace
                    elif action in {"open_app_workspace", "switch_workspace", "move_window_workspace"}:
                        current = str(guarded.get("workspace_no", "")).strip()
                        if current != requested_workspace:
                            print(
                                f"[Guardrail] Workspace override: {action} {current or '-'} -> {requested_workspace}"
                            )
                        guarded["workspace_no"] = requested_workspace

                    guarded_actions.append(guarded)
                actions = guarded_actions

            if all(a.get("action", "none") == "none" for a in actions):
                print(f"\n[Executor] Action: none")
                history.append({"role": "assistant", "content": consciousness})

                saved = memory.save(user, consciousness)
                if saved:
                    print("[Saved to memory]")
                print()
                if use_mic:
                    speak(consciousness)
                break


            history.append({"role": "assistant", "content": consciousness})

            seen = set()
            unique_actions = []
            for a in actions:
                key = str(sorted(a.items()))
                if key not in seen:
                    seen.add(key)
                    unique_actions.append(a)
            actions = unique_actions

            all_results = []
            ran_web_tool = False
            for i, action_dict in enumerate(actions):
                action_name = action_dict.get("action", "none")
                if action_name == "none":
                    continue

                _WEB_TOOLS = {"web_research", "read_page", "deep_research", "crawl_page"}
                action_key = str(sorted(action_dict.items()))
                type_key = f"__type__{action_name}"
                if action_key in executed_actions or (action_name in _WEB_TOOLS and type_key in executed_actions):
                    print(f"\n[Skipped] Same action already executed: {action_name}")
                    continue
                executed_actions.add(action_key)
                if action_name in _WEB_TOOLS:
                    executed_actions.add(type_key)

                detail = action_dict.get("command", "") or action_dict.get("file", "") or "-"
                label = f"[Executor] Action {i+1}/{len(actions)}: {action_name} → {detail}" if len(actions) > 1 else f"[Executor] Action: {action_name} → {detail}"
                print(f"\n{label}")

                result = execute_tool(action_dict)
                result_safe = str(result).encode('utf-8', errors='replace').decode('utf-8')
                print(f"\n[Observation] {result_safe[:300]}{'...' if len(result_safe) > 300 else ''}\n")
                all_results.append(result)
                if action_name in {"web_research", "read_page"} and not result.startswith("❌"):
                    ran_web_tool = True
                tracker.update(action_dict)

            if not all_results:
                print("[All actions already executed, stopping loop.]")
                break

            combined_result = "\n".join(all_results)

            failed = sum(1 for r in all_results if r.startswith("\u274c"))
            if failed > 0:
                error_count += failed
            else:
                error_count = 0

            if error_count >= 3:
                print("[WARNING] 3+ consecutive errors. Stopping loop.")
                history.append({"role": "assistant", "content": consciousness})
                break

            _observation_suffix = (
                "\nWARNING: Web research ('web_research'/'read_page') has ALREADY been completed this round. "
                "Do NOT use these tools AGAIN. Present the result to the user and finish."
                if ran_web_tool else ""
            )
            history.append({
                "role": "user",
                "content": (
                    f"OBSERVATION RESULT (command ALREADY executed, do not re-run!):\n{combined_result}\n\n"
                    "Show this result to the user AS-IS. Do NOT run the same command again. "
                    "If a DIFFERENT action is needed, state it; otherwise inform the user of the result."
                    + _observation_suffix
                )
            })

            history = trim_history(history)

            if loop == BASE_MAX_LOOPS - 1 and max_loops == BASE_MAX_LOOPS:
                try:
                    user_approval = input(f"🤔 {ASSISTANT_NAME}: 8 loops reached. Continue? (y/n): ").strip().lower()
                    if user_approval in ("y", "yes"):
                        max_loops = EXTENDED_MAX_LOOPS
                        print(f"[Loop limit extended to {EXTENDED_MAX_LOOPS}]")
                    else:
                        print("[Loop stopped by user]")
                        break
                except (KeyboardInterrupt, EOFError):
                    print("\n[Loop interrupted]")
                    break

            loop += 1
        else:
            print(f"\n[WARNING] Maximum loop limit ({max_loops}) reached. {ASSISTANT_NAME} stopping.")


if __name__ == "__main__":
    main()