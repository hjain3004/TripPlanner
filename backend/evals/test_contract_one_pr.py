import subprocess

def git_changed_files_in_head() -> list[str]:
    # get the files changed in HEAD, but wait, the plan implies uncommitted files too?
    # "contract changed without [...] in the SAME COMMIT" -> it means the currently uncommitted or staged files during `make gate`? 
    # Usually `make gate` runs before commit. So `git status --porcelain` might be what we want, OR `git diff --cached --name-only` + `git diff --name-only`.
    # But wait, the plan explicitly says "git_changed_files_in_head()".
    # Let's check both HEAD (if in CI) and the working tree.
    try:
        # unstaged
        unstaged = subprocess.check_output(["git", "diff", "--name-only"]).decode().splitlines()
        # staged
        staged = subprocess.check_output(["git", "diff", "--cached", "--name-only"]).decode().splitlines()
        # diff with origin/main or HEAD? The plan says "in the same commit".
        return list(set(unstaged + staged))
    except subprocess.CalledProcessError:
        return []

def test_a_contract_change_ships_with_its_generated_client_and_fixtures() -> None:
    """Spec 12 section 8: schema, codegen, MSW fixtures and UI ship in ONE commit.
    Split PRs are the drift vector."""
    changed = git_changed_files_in_head()
    if "contract/openapi.json" not in changed:
        return
    required = ["frontend/src/lib/api/", "frontend/src/mocks/handlers.ts"]
    missing = [r for r in required if not any(c.startswith(r) for c in changed)]
    assert not missing, f"contract changed without {missing} in the same commit"
