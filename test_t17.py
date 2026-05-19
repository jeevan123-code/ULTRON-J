src  = open('templates/index.html', encoding='utf-8').read()
src2 = open('app.py',               encoding='utf-8').read()
src3 = open('llm_engine.py',        encoding='utf-8').read()

assert 'provider-select' in src,           'dropdown id missing in index.html'
assert 'ollama:mistral'  in src,           'ollama option missing in index.html'
dchat_start = src.index('async function doChat')
dchat_block = src[dchat_start:dchat_start+800]
assert 'provider-select' in dchat_block,   'provider-select not read in doChat'
assert 'provider:prov'   in dchat_block,   'provider not in fetch payload'
print('index.html: dropdown OK, doChat payload OK')

assert "data.get('provider'" in src2,       'provider not extracted in app.py'
assert "ollama:" in src2,                   'ollama branch missing in app.py'
assert 'force_provider=provider' in src2,   'force_provider not passed to stream_llm'
print('app.py: provider OK, ollama branch OK, force_provider OK')

assert 'force_provider: str' in src3,       'force_provider param missing in llm_engine.py'
assert 'order = [force_provider]' in src3,  'single-provider order missing'
print('llm_engine.py: force_provider OK, single-order OK')

print('ALL T17 CHECKS PASSED')
