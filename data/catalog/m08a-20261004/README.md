# M08A 실제 상담 목록

버전: m08a-20261004-v2 · 검토일: 2026-10-04 · COMPLETE_VERIFIED

사용자가 M08A 작성을 지시하여 실제 M08 원문을 기준으로 편집했다. 시험 fixture를 재사용하지 않았다. 12개 공간·35개 시설물·45개 증상·54개 질문으로 구성한다. 원문 문장 전체는 접근 제한된 M08 자료에 보존하며, 이 디렉터리는 서비스 선택 목록과 검토 메타데이터다.

- catalog.json: 검토·게시할 완성 목록
- review.json: 목록 SHA256, M08 원문 manifest 해시, 항목·질문별 근거, 조문 coverage, 검토 범위

검토 해시는 파일 바이트 기준이다. `.gitattributes`에서 카탈로그 JSON의 자동 줄바꿈 변환을 끄고 검토 당시 바이트를 보존한다. JSON을 편집하면 해시와 검토 기록을 함께 갱신해야 한다.

질문은 관찰 사실을 수집한다. 설계도서·외부 기준·현장 검사가 필요한 사항은 추정하지 않으며 모든 질문에 모름을 제공한다. 공간/시설 모름 경로도 있다. 법적 하자 기준 수치와 LH 비용/교체 조건은 판정 로직에 넣지 않았다. 증상 목록은 법령의 모든 문장·조건을 대체하지 않는다.

제6조의2는 사용 형태 질문, 제44조는 선택적 재해 맥락 질문에 반영한다. 법정 전유/공용 구분이나 재해 면책 여부는 이 답만으로 확정하지 않는다. 제35조 적용례는 사업계획승인 신청일을 묻는다. 별표4의 손상 표현 및 제45조 외부 인용은 관찰 분류만 제공한다.

위험 정책: immediate-danger=YES와 detail-light-defect=BURN_SMOKE/SPARK는 안전 확인 우선으로 중단한다. 나머지 조건이 맞아도 LH 운영 근거가 없으면 NEED_CONFIRMATION이다. UNKNOWN은 안전하다는 판정이 아니다.

조건부 분기: detail-leak=FLOWING일 때 leak-pattern을 보여 주고, 물 자국만 있다고 바꾸면 해당 답을 제거한다. 결로 난방 여부·설치 주체, 바닥구조의 신청 시점, 뿌리 결속재와 준공 시점도 해당 증상에서 확인한다. 재해 질문만 선택이고 나머지는 필수(모름 답 허용)다.

아래 공간·동의어는 쉬운 이용을 위한 UX 편집이며 법령상 적용 대상을 확대하거나 동등성을 확정하지 않는다. 사람의 법률/LH 운영 승인은 포함하지 않는다.

| 증상 ID | 표시명 | 시설 ID | 출처 |
| --- | --- | --- | --- |
| concrete-crack | 콘크리트가 갈라졌어요 | concrete | 제7조 |
| rebar-exposed | 콘크리트 안의 철근이 보여요 | concrete | 제8조 |
| plaster-damage | 미장 면이 갈라지거나 떨어져요 | finish | 제9조 |
| paint-damage | 도장이 갈라지거나 벗겨져요 | finish | 제9조 |
| leak | 물이 새거나 물 자국이 있어요 | waterproof, pipe, window, concrete | 제10조, 별표 2 |
| joint-defect | 바닥 줄눈이 없거나 도면과 달라요 | joint | 제11조 |
| tie-remains | 벽에 고정 철물이 튀어나오거나 구멍이 남았어요 | concrete | 제12조 |
| penetration-gap | 배관·배선 주위가 덜 메워졌어요 | penetration | 제13조 |
| duct-finish | 덕트 벽면 마감이 빠져 있어요 | duct | 제14조 |
| condensation | 표면에 물방울이나 곰팡이가 생겨요 | finish, window, floor | 제15조 |
| sink-unfinished | 싱크대 아래·뒤쪽 마감이 없어요 | sink | 제16조 |
| bath-threshold | 욕실 문턱이 낮거나 도면과 달라요 | bath-finish | 제17조 |
| mirror-color | 욕실 거울의 색이 변했어요 | bath-finish | 제17조 |
| tile-defect | 타일이 깨지거나 들뜨고 떨어져요 | tile | 제18조 |
| trench-defect | 배수로가 없거나 물이 고여요 | drain | 제19조 |
| drain-slope | 물이 배수구로 흐르지 않고 고여요 | drain, floor | 제20조 |
| door-edge | 목재 문 위·아래 끝면 마감이 없어요 | door | 제21조 |
| opening-function | 문·창문이 잘 닫히거나 잠기지 않아요 | door, window | 제22조 |
| light-wiring | 조명 연결 배선이 도면과 달라요 | light | 제23조 |
| light-defect | 조명이 안 켜지거나 고정 상태가 불량해요 | light | 제24조 |
| air-defect | 환풍기·에어컨·후드가 작동하지 않아요 | air | 제25조 |
| heating-control | 방별로 난방을 조절할 수 없어요 | heating | 제26조 |
| sanitary-defect | 수전·위생기구가 새거나 작동이 불량해요 | sanitary | 제27조 |
| intercom-defect | 인터폰의 통화·영상·연결이 불량해요 | intercom | 제28조 |
| cctv-defect | CCTV가 없거나 화면 식별이 어려워요 | cctv | 제29조 |
| tree-health | 나무가 말라 죽거나 쓰러졌어요 | tree | 제30조 |
| root-binding | 나무 뿌리의 결속재가 지표면에 보여요 | tree | 제31조 |
| tree-planting | 나무 종류·식재가 도면과 달라요 | tree | 제32조 |
| tree-size | 나무의 크기가 도면보다 작아 보여요 | tree | 제33조 |
| wallpaper-defect | 벽지가 들뜨거나 주름·틈이 생겼어요 | wallpaper | 제34조 |
| floor-finish | 바닥재가 깨지거나 들뜨고 삐걱거려요 | floor | 제35조 |
| floor-layer | 바닥 구성층이 도면과 달라요 | floor | 제35조, 부칙 제2025-58호 제2조 |
| stone-defect | 석재가 깨지거나 떨어지고 변색돼요 | stone | 제36조 |
| furniture-defect | 설치된 가구가 깨지거나 잘 열리지 않아요 | furniture | 제37조 |
| insulation-defect | 보온재가 없거나 배관이 얼었어요 | insulation | 제38조 |
| appliance-defect | 설치된 가전이 없거나 작동하지 않아요 | appliance | 제39조 |
| elevator-defect | 승강기의 작동·문턱·마감에 문제가 있어요 | elevator | 제40조 |
| pavement-defect | 보도·차도가 깨지거나 솟고 물이 고여요 | pavement | 제41조 |
| parking-defect | 주차장 폭·보호시설·마감에 문제가 있어요 | parking-fixture | 제42조, 별표 3 |
| retaining-defect | 옹벽에 균열·침하·배수 문제가 보여요 | retaining | 제43조, 별표 4 |
| fire-defect | 소방 설비의 설치·작동을 확인하고 싶어요 | fire | 제45조 |
| gas-defect | 가스 설비의 설치·기능에 문제가 있어요 | gas | 제45조 |
| electric-defect | 전기 설비의 상태를 확인하고 싶어요 | electric | 제45조 |
| railing-defect | 난간의 설치 상태를 확인하고 싶어요 | railing | 제45조 |
| unknown | 증상을 잘 모르겠어요 | concrete, finish, waterproof, pipe, window, joint, penetration, duct, sink, bath-finish, tile, drain, door, light, air, heating, sanitary, intercom, cctv, tree, wallpaper, floor, stone, furniture, insulation, appliance, elevator, pavement, parking-fixture, retaining, fire, gas, electric, railing, unknown | UX_POLICY |

게시 이력: v1의 원본·검토 정보는 releases/에 보존했다. v2에서 단지 외부 공간의 콘크리트·벽 마감·방수 부위 연결을 보완했다. 게시본은 수정하지 않고 새 버전으로 게시한다.
