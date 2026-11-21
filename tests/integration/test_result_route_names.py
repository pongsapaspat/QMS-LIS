from app.main import app


def test_result_queue_route_names_keep_web_redirects_separate_from_api() -> None:
    assert str(app.url_path_for("verification_queue")) == "/results/verification"
    assert str(app.url_path_for("release_queue")) == "/results/release"
    assert str(app.url_path_for("api_verification_queue")) == (
        "/api/v1/results/verification-queue"
    )
    assert str(app.url_path_for("api_release_queue")) == "/api/v1/results/release-queue"
    assert str(app.url_path_for("worklist")) == "/worklist"
    assert str(app.url_path_for("api_result_worklist")) == "/api/v1/results/worklist"
