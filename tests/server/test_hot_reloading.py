# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import yaml
from click.testing import CliRunner

from deepsparse.server.cli import config, task
from deepsparse.server.config import EndpointConfig, ImageSizesConfig, ServerConfig
from deepsparse.server.config_hot_reloading import (
    _ContentMonitor,
    _diff_generator,
    _update_endpoints,
    endpoint_diff,
)
from deepsparse.server.server import start_server


def test_no_route_not_in_diff():
    no_route = EndpointConfig(task="b", model="c")
    old = ServerConfig(endpoints=[])
    new = ServerConfig(endpoints=[no_route])

    added, removed = endpoint_diff(old, new)
    assert added == []
    assert removed == []

    added, removed = endpoint_diff(new, old)
    assert added == []
    assert removed == []


def test_added_removed_endpoint_diff():
    route1 = EndpointConfig(task="b", model="c", route="1")
    route2 = EndpointConfig(task="b", model="c", route="2")
    route3 = EndpointConfig(task="b", model="c", route="3")
    old = ServerConfig(endpoints=[route1, route2])
    new = ServerConfig(endpoints=[route1, route3])

    added, removed = endpoint_diff(old, new)
    assert added == [route3]
    assert removed == [route2]


def test_endpoint_diff_modified_model():
    default_cfg = dict(model="a", route="1", task="b")
    route1 = EndpointConfig(**default_cfg)
    old = ServerConfig(endpoints=[route1])

    all_fields = dict(
        model="b",
        task="c",
        batch_size=2,
        bucketing=ImageSizesConfig(image_sizes=[], kwargs=dict(a=2)),
    )
    for key, value in all_fields.items():
        cfg = default_cfg.copy()
        cfg[key] = value
        route2 = EndpointConfig(**cfg)
        new = ServerConfig(endpoints=[route2])
        added, removed = endpoint_diff(old, new)
        assert added == [route2]
        assert removed == [route1]


@patch("requests.post")
@patch("requests.delete")
def test_update_endpoints(delete: MagicMock, post: MagicMock):
    route1 = EndpointConfig(task="b", model="c", route="1")
    route2 = EndpointConfig(task="b", model="c", route="2")
    route3 = EndpointConfig(task="b", model="c", route="3")
    old = ServerConfig(endpoints=[route1, route2])
    new = ServerConfig(endpoints=[route1, route3])

    # NOTE: no_route not included in removed since we can't detect
    # changes for this without route specified
    added, removed = _update_endpoints("", old, new)
    assert added == [route3]
    assert removed == [route2]

    delete.assert_called_once_with("", json=route2.dict())
    post.assert_called_once_with("", json=route3.dict())


def test_file_changes(tmp_path: Path):
    # NOTE: this sleeps between each write because timestamps
    # only have a certain resolution

    path = tmp_path / "file.txt"
    path.write_text("")

    content = _ContentMonitor(path)

    assert content.maybe_update_content() is None

    time.sleep(0.1)
    path.write_text("first")
    assert content.maybe_update_content() == ("", "first")

    time.sleep(0.1)
    assert content.maybe_update_content() is None

    time.sleep(0.1)
    path.write_text("second")
    assert content.maybe_update_content() == ("first", "second")


@patch("requests.post")
@patch("requests.delete")
def test_file_monitoring(delete_mock, post_mock, tmp_path: Path):
    path = str(tmp_path / "cfg.yaml")
    versions_path = tmp_path / "cfg.yaml.versions"

    cfg1 = ServerConfig(endpoints=[])
    with open(path, "w") as fp:
        yaml.safe_dump(cfg1.dict(), fp)

    diffs = _diff_generator(path, "", 0.1)
    assert next(diffs) is None
    assert not versions_path.exists()

    cfg2 = ServerConfig(endpoints=[EndpointConfig(task="a", model="b", route="1")])
    with open(path, "w") as fp:
        yaml.safe_dump(cfg2.dict(), fp)
    assert next(diffs) == (cfg1, cfg2, path + ".versions/0.yaml")
    assert versions_path.exists()

    assert next(diffs) is None

    cfg3 = ServerConfig(endpoints=[EndpointConfig(task="a", model="c", route="1")])
    with open(path, "w") as fp:
        yaml.safe_dump(cfg3.dict(), fp)
    assert next(diffs) == (cfg2, cfg3, path + ".versions/1.yaml")

    all_files = sorted(map(str, tmp_path.rglob("*")))
    all_files = [f.replace(str(tmp_path), "") for f in all_files]
    assert all_files == [
        "/cfg.yaml",
        "/cfg.yaml.versions",
        "/cfg.yaml.versions/0.yaml",
        "/cfg.yaml.versions/1.yaml",
    ]

    for idx, v in enumerate(["0.yaml", "1.yaml"]):
        with open(str(versions_path / v)) as fp:
            content = fp.read()
            assert content.startswith(f"# Version {idx} saved at")
            yaml.safe_load(content)


@mock.patch("uvicorn.run")
@mock.patch("deepsparse.server.server.start_config_watcher")
def test_hot_reload_config_with_start_server(
    watcher_patch: mock.Mock, run_patch: mock.Mock, tmp_path: Path
):
    cfg = ServerConfig(endpoints=[], num_cores=1, num_workers=1, loggers=None)
    cfg_path = str(tmp_path / "cfg.yaml")
    with open(cfg_path, "w") as fp:
        yaml.safe_dump(cfg.dict(), fp)

    # setting to False calls uvicorn.run(), but NOT start_config_watcher
    start_server(cfg_path, hot_reload_config=False)
    assert run_patch.call_count == 1
    assert watcher_patch.call_count == 0

    # setting to True calls uvicorn.run() AND start_config_watcher
    start_server(cfg_path, hot_reload_config=True)
    assert run_patch.call_count == 2
    assert watcher_patch.call_count == 1


@mock.patch("deepsparse.server.cli.start_server")
def test_task_cli_hot_reload(start_server):
    runner = CliRunner()

    # no flag sets hot_reload_config to False
    runner.invoke(task, ["qa"])
    _, kwargs = start_server.call_args
    assert kwargs["hot_reload_config"] is False

    # using flag sets hot_reload_config to True
    runner.invoke(task, ["qa", "--hot-reload-config"])
    _, kwargs = start_server.call_args
    assert kwargs["hot_reload_config"] is True


@mock.patch("deepsparse.server.cli.start_server")
def test_config_cli_hot_reload(start_server, tmp_path: Path):
    runner = CliRunner()

    # no flag sets hot_reload_config to False
    runner.invoke(config, [str(tmp_path)])
    _, kwargs = start_server.call_args
    assert kwargs["hot_reload_config"] is False

    # using flag sets hot_reload_config to True
    runner.invoke(config, [str(tmp_path), "--hot-reload-config"])
    _, kwargs = start_server.call_args
    assert kwargs["hot_reload_config"] is True
