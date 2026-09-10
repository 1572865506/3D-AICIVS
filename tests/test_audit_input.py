"""输入和静态服务边界回归。"""
from pathlib import Path
import pytest
from backend.api.static_files import public_file
from backend.solver_v2.api.adapter import InputAdapter


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 0])
def test_reject_invalid_dimension(value):
    with pytest.raises(ValueError):
        InputAdapter.parse_cargo_list([{'w':value,'d':1,'h':1}])


def test_private_files_not_served(tmp_path):
    for name in ['index.html','.env','backend/server.py','frontend/src/app.js']:
        p=tmp_path/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text('test')
    assert public_file(tmp_path,'/') == str(tmp_path/'index.html')
    for url in ['/.env','/backend/server.py','/.git/config','/frontend/src/../../backend/server.py','/%2eenv']:
        assert public_file(tmp_path,url) is None


def test_duplicate_sku_rejected():
    with pytest.raises(ValueError):
        InputAdapter.parse_cargo_list([{'sku':'A'}, {'sku':'A'}])


def test_public_symlink_cannot_expose_private_file(tmp_path):
    (tmp_path/'frontend/src').mkdir(parents=True)
    (tmp_path/'.env').write_text('private')
    (tmp_path/'frontend/src/leak.js').symlink_to(tmp_path/'.env')
    assert public_file(tmp_path,'/frontend/src/leak.js') is None


@pytest.mark.parametrize('quantity',[1.5,-1,float('inf'),float('nan')])
def test_quantity_must_be_integer(quantity):
    with pytest.raises(ValueError):InputAdapter.parse_cargo_list([{'quantity':quantity}])
