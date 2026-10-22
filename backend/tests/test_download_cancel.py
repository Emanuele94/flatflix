"""Cancel and remove through the API against FakeQbit (DOWN-05, DOWN-06, D-32..D-35).

The browser names a download by its opaque id only; these tests watch what the backend sent to
qBittorrent (`fake.deleted`) and what the list shows afterwards.
"""

import httpx

from tests.fakeqbit import FakeQbit

HASH = "a" * 40


async def test_cancelling_an_in_progress_download_deletes_the_torrent_and_its_files(
    user_api: httpx.AsyncClient, fake_qbit: FakeQbit
) -> None:
    fake_qbit.add_torrent_row(HASH, category="Film", state="downloading", progress=0.4)
    (item,) = (await user_api.get("/api/downloads")).json()["items"]

    response = await user_api.delete(f"/api/downloads/{item['id']}")

    assert response.status_code == 204
    assert fake_qbit.deleted == [(HASH, True)]
    assert (await user_api.get("/api/downloads")).json() == {"items": []}
