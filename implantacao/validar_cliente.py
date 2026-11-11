"""Executar em OUTRO computador. HTTPS obrigatorio para login e gravacao."""
import argparse
from datetime import datetime
import getpass
import http.cookiejar
import json
from pathlib import Path
import re
import secrets
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--saida', required=True)
    args = parser.parse_args()
    base = args.url.rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in {'http','https'} or parsed.username or parsed.password:
        raise RuntimeError('URL invalida')
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, values=None):
        data = urllib.parse.urlencode(values).encode() if values is not None else None
        with opener.open(base + path, data=data, timeout=60) as response:
            if urllib.parse.urlsplit(response.url).netloc != parsed.netloc:
                raise RuntimeError('Redirecionamento para outro servidor; validacao cancelada')
            return response.status, response.url, response.read().decode('utf-8')
    def csrf(body):
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', body)
        if not match: raise RuntimeError('Token CSRF ausente')
        return match.group(1)
    report = {'url':base,'timestamp':datetime.now().astimezone().isoformat(),
              'same_client_after_reboot_required':True}
    status,url,body = request('/login')
    report['login_page_http_status'] = status
    if parsed.scheme == 'http':
        report['connectivity_only_no_credentials_sent'] = True
    else:
        password = getpass.getpass('Senha do login master do aplicativo (nao PostgreSQL): ')
        _,url,body = request('/login',{'usuario':'00000000000','senha':password,'csrf_token':csrf(body)})
        if '/login' in url:
            raise RuntimeError('Login master nao autenticou')
        report['master_login'] = True
        cpf = getpass.getpass('CPF de um cidadao existente para a consulta (oculto): ')
        cpf = ''.join(c for c in cpf if c.isdigit())
        if len(cpf)!=11: raise RuntimeError('CPF de consulta invalido')
        status,url,body = request('/dados/cidadaos?'+urllib.parse.urlencode({'buscar':'1','cpf':cpf}))
        report['citizen_query'] = status==200 and '/login' not in url and cpf in re.sub(r'[^0-9]','',body)
        booking = int(input('ID do agendamento existente: '))
        status,url,body = request('/dados/agendamentos?editar='+str(booking))
        report['booking_opened'] = status==200 and f'/agendamentos/{booking}/editar' in body
        _,_,body = request('/dados/motoristas')
        marker = ('VALIDACAO_REDE_'+secrets.token_hex(8)).upper()
        _,_,body = request('/dados/motoristas/novo',{'cracha':'987654320','nome':marker,'ativo':'1','csrf_token':csrf(body)})
        row = next((r for r in re.findall(r'<tr.*?</tr>',body,re.S) if marker in r),None)
        if not row: raise RuntimeError('Gravacao de teste nao confirmada')
        matched = re.search(r'/dados/motoristas/(\d+)/excluir',row)
        if not matched: raise RuntimeError('ID do teste nao identificado')
        record_id = int(matched.group(1))
        _,_,body = request(f'/dados/motoristas/{record_id}/excluir',{'csrf_token':csrf(body)})
        report.update(test_write=True,test_record_inactivated=True,test_marker=marker,test_driver_id=record_id)
        # A exclusao e logica e auditada. Limpeza fisica opcional e restrita no servidor.
        request('/sair',{'csrf_token':csrf(body)})
        report['success'] = report['citizen_query'] and report['booking_opened']
    Path(args.saida).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('VALIDACAO_NAO_APROVADA:',type(error).__name__)
        raise SystemExit(1)
