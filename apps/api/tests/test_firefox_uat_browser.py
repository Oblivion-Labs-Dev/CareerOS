"""Explicitly opted-in Firefox contracts, entirely on loopback."""
import asyncio
import os
import pytest
from app.services.uat.firefox import BrowserConfig, TargetPolicy, FirefoxUAT
from app.services.uat.fixtures import fixture_server

pytestmark = pytest.mark.skipif(os.getenv('CAREEROS_FIREFOX_UAT') != '1', reason='Opt-in Firefox browser suite')
PROFILE = {'firstName':'Test','lastName':'Candidate','fullName':'Test Candidate','email':'test@example.invalid',
           'phone':'2065550100','country':'United States','linkedin':'https://example.invalid/test'}


@pytest.mark.parametrize('engine',['firefox','camoufox'])
@pytest.mark.parametrize('portal',['greenhouse','lever','himalayas'])
def test_fill_verify_attach_and_fixture_commit(tmp_path, engine, portal):
    import pymupdf
    path = tmp_path / 'fixture.pdf'
    with pymupdf.open() as doc:
        doc.new_page().insert_text((36,36),'Test Candidate - UAT fixture')
        doc.save(path)
    async def run(url):
        async with FirefoxUAT(BrowserConfig(engine=engine), TargetPolicy((url,),fixture=True)) as browser:
            await browser.open(url+'/'+portal)
            if portal == 'himalayas':
                await browser.page.frame_locator('iframe').locator('form').wait_for()
            result = await browser.execute_form_fill(PROFILE,path)
            assert result['status']=='complete', result
            assert all(r['status']=='filled' for r in result['fields']), result
            root = browser.page.frames[-1] if portal=='himalayas' else browser.page
            # Existing application tracking intentionally tags contact email.
            assert await root.get_by_label('Email',exact=True).input_value()=='test+career@example.invalid'
            assert await root.get_by_label('Country',exact=True).input_value()=='US'
            assert await root.get_by_label('Resume',exact=True).evaluate('(el)=>el.files[0].name')=='fixture.pdf'
            assert (await browser.safely_commit_form(root.get_by_role('button',name='Submit fixture'),root.locator('#receipt')))['status']=='confirmed'
            with pytest.raises(ValueError):
                await browser.safely_commit_form(root.get_by_role('button'),root.locator('#receipt'))
    with fixture_server() as url:
        asyncio.run(run(url))


@pytest.mark.parametrize('engine',['firefox','camoufox'])
def test_challenge_lock_timeout_and_unknown_field_stop(engine):
    async def run(url):
        for route in ('challenge','expired','locked'):
            async with FirefoxUAT(BrowserConfig(engine=engine),TargetPolicy((url,),fixture=True)) as browser:
                assert (await browser.open(url+'/'+route))['verification']=='challenge_or_lock'
                with pytest.raises(ValueError,match='human review'):
                    await browser.execute_form_fill(PROFILE)
        async with FirefoxUAT(BrowserConfig(engine=engine),TargetPolicy((url,),fixture=True)) as browser:
            await browser.open(url+'/greenhouse')
            result=await browser.execute_form_fill({})
            assert result['status']=='needs_review'
            assert not any(r['status']=='filled' for r in result['fields'])
    with fixture_server() as url:
        asyncio.run(run(url))


@pytest.mark.parametrize('engine',['firefox','camoufox'])
def test_custom_combobox_and_seeded_pacing(engine):
    async def run(url):
        async with FirefoxUAT(BrowserConfig(engine=engine,paced=True),TargetPolicy((url,),fixture=True)) as browser:
            await browser.open(url+'/custom')
            result=await browser.execute_form_fill(PROFILE)
            assert result['status']=='complete',result
            assert await browser.page.locator('#country').input_value()=='United States'
    with fixture_server() as url:
        asyncio.run(run(url))
