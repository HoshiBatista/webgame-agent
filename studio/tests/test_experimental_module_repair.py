from generation.artifacts import materialize, sha256
from generation.providers.fake import fixture_response
from generation.scene import PATH
from studio.models import Revision
from studio.tasks import request_for
from studio.tests.test_pro_parallel import context as context  # noqa: F401
from studio.tests.test_pro_parallel import new_run


def test_new_experiment_issues_one_file_permission_and_older_runs_keep_saved_contract(context):
    run = new_run(context)
    game = materialize(fixture_response(with_assets=True), operation='create', helper_catalog=run.helper_catalog)
    base = Revision.objects.create(chat=run.chat, run=run, number=1, files=game['files'],
                                  file_hashes=game['file_hashes'], artifact_hash=game['artifact_hash'],
                                  html=game['html'], checks=game['checks'])
    finding = {'code': 'javascript_syntax', 'path': 'game.js',
               'location': 'source', 'file_hash': sha256(base.files['game.js'])}
    assert PATH in run.helper_catalog
    request = request_for(run, base, [finding])
    assert request['operation'] == 'repair'
    assert request['module_repair']['targets'] == {'game.js': base.file_hashes['game.js']}
    assert request['module_repair']['scope'] == 'one_file'
    run.pro_parallel = False
    assert request_for(run, base, [finding])['module_repair']['scope'] == 'single_module'
    run.pro_parallel = True
    del run.helper_catalog[PATH]
    assert request_for(run, base, [finding])['module_repair']['scope'] == 'single_module'
