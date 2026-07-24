import yaml

from evals.transfer_harness import GOLDEN_DIR, run_transfer_case


def test_transfer_results_are_byte_identical() -> None:
    demo = yaml.safe_load((GOLDEN_DIR / "transfer_demo.yaml").read_text())
    first = run_transfer_case(demo).model_dump_json()
    second = run_transfer_case(demo).model_dump_json()
    assert first.encode() == second.encode()


def test_every_transfer_edge_case_is_byte_identical() -> None:
    payload = yaml.safe_load((GOLDEN_DIR / "transfer_edge_cases.yaml").read_text())
    for case in payload["cases"]:
        first = run_transfer_case(case).model_dump_json()
        second = run_transfer_case(case).model_dump_json()
        assert first == second, case["name"]
