# Codex credential 경계

Language: [English](credential-boundary.md) | 한국어

## 목적

Harness는 coding Agent의 작업 방식을 통제하지 않는다. Codex의 permission-profile
경로가 활성화된 경우 credential 기밀성은 Harness Core 밖에서 repository의
`.codex/config.toml`에 정의한 profile로 강제한다.

이 profile은 Codex built-in `:workspace` permission을 상속한다. 일반적인 workspace
탐색·수정·명령 실행은 유지하면서 credential을 포함할 가능성이 높은 좁은 경로 집합의
읽기와 쓰기만 거부한다. lifecycle hook, command parsing, approval state, Harness
runtime state machine은 추가하지 않는다.

## 기본 차단 대상

Workspace 규칙은 다음을 차단한다.

- 아래의 portable scan-depth 한계 안에서 설정된 workspace root 아래에 있는 `.env`,
  `.env.*`, `.envrc`;
- `.key`로 끝나는 private-key 파일;
- `key.json`, `credentials.json`, service-account 변형 같은 일반적인 credential
  JSON 파일명;
- 일반적인 SSH private-key 파일명.

또한 Codex, SSH, AWS, Azure, Google Cloud, GitHub CLI, Docker, Kubernetes, npm,
PyPI, Git, netrc의 사용자 credential 경로를 정확한 경로로 차단한다. 이 목록 밖의
directory와 파일은 built-in `:workspace` 동작을 유지한다.

Linux, WSL, native Windows에서 Codex는 sandbox 시작 전에 범위가 정해지지 않은 `**`
deny glob을 미리 확장할 수 있다. 이 profile은 startup 작업량을 제한하기 위해
`glob_scan_max_depth = 8`을 유지한다. 따라서 해당 platform에서 workspace-relative
glob의 portable 보장 범위는 설정된 scan depth까지이며, 그보다 깊이 중첩된 파일은 이
repository 정책의 보장 범위 밖이다.

정확한 `.env.example` 이름은 deny pattern에서 제외해 runtime 값 없이 문서화된
환경변수 계약을 볼 수 있게 한다. Codex permission profile의 filesystem glob은
의도적으로 `deny`만 지원하므로 약한 read hook 대신 negative character class로 예외를
표현한다. Example 파일에는 placeholder 값만 있어야 하며, 실수로 secret을 넣었다면
이 예외가 그 값을 안전하게 만들지는 않는다.

## Process environment

환경변수 이름에 `KEY`, `SECRET`, `TOKEN`이 포함되면 제외하는 Codex 기본
case-insensitive filter를 유지한다. 프로젝트는 `CREDENTIAL`, `PASSWORD`, `PASSWD`가
포함된 이름도 제외한다. 일반적인 build와 test discovery를 유지하도록 그 밖의
환경변수는 계속 상속한다.

이 정책은 Codex가 실행하는 subprocess에 적용된다. Harness는 check stdout과 stderr를
그대로 기록하므로 외부 경로에서 얻은 secret 값을 check가 출력해서는 안 된다.

## 활성화와 override 경계

Permission profile은 legacy sandbox 설정과 결합되지 않는다. 로드된 config 중 하나에
`sandbox_mode`가 있거나, CLI에 `--sandbox`가 전달되거나, 선택한 config profile이
`sandbox_mode`를 설정하면 Codex는 legacy sandbox를 사용하고 `default_permissions`를
무시한다. 이 경계에 의존하기 전에 `sandbox_mode`와 `[sandbox_workspace_write]`를
제거해야 한다. Managed deployment는 repository runtime guard를 추가하지 말고 legacy
설정을 제거한 뒤 `allowed_permission_profiles`와 managed `default_permissions`를
사용해야 한다.

Project 범위의 `.codex/config.toml`은 trusted project에서만 로드되며, 새 Codex
session이 설정을 해석할 때 적용된다. 이미 실행 중인 session의 permission을 소급해
바꾸지는 않는다.

이 profile은 안전한 기본값이지 관리자가 강제한 immutable policy는 아니다. 실제
접근이 필요하면 사용자가 의도적으로 다른 permission profile을 고르거나 sandbox 밖
명령을 승인할 수 있다. 이때는 정확한 파일과 목적을 지정해야 하며, 광범위한 영구
예외는 이 경계를 무력화한다.

Codex permission profile은 Codex 0.138.0 이상이 필요하고 현재 beta다. 이전 client에는
부분적인 hook fallback을 추가하지 말고 client를 업그레이드해야 한다.

## 검증

Repository test suite는 commit된 profile 계약을 검증한다. 호환되는 `codex` 실행 파일이
있으면 synthetic 값을 사용하는 local sandbox smoke test도 실행해 `.env`, 대표적인
`.env.*` 변형, `.envrc`, `key.json`을 읽을 수 없고 정확한 `.env.example` 이름은 root와
설정된 scan depth 안에서 읽을 수 있는지 확인한다. Smoke test는 profile을 명시적으로
선택하므로 profile 정의를 검증할 뿐, 모든 사용자의 default session이 이 profile을
선택했다는 사실까지 증명하지는 않는다.
