Web-R_Data_RBloggers Sync Patch (완성본)

포함 파일:
- .github/workflows/rbloggers_crawl.yml

핵심 변경점:
1) Web-R sync 호출 시 인증 헤더를 X-WEBR-SYNC-TOKEN 으로 통일
2) push 이후 HEAD sha 사용
3) 기본은 '이번 실행에서 변경된 by_created/**/*.json'만 sync
4) 수동 실행(workflow_dispatch)에서 resync=true 옵션으로 by_created 전체(또는 특정 월) 강제 재동기화
5) 504 타임아웃 방지를 위해 files를 배치(기본 200개)로 나눠 여러 번 POST
   - 배치 크기 조절: Actions env WEBR_SYNC_BATCH=100 등으로 설정 가능

사용:
- 스케줄 실행: 자동(diff 기반) sync
- 강제 재동기화:
  Actions > 워크플로우 선택 > Run workflow
    resync = true
    resync_month = 2026/01  (선택, 비우면 전체)
