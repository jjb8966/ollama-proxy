# -*- coding: utf-8 -*-
"""
CLI 명령어

쿼터 조회 등의 CLI 명령을 정의합니다.
"""

import click
import sys
import os

# 상위 디렉토리를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.services.quota_service import get_quota_service
from src.models.quota import QuotaModel


@click.group()
def cli():
    """ollama-proxy CLI 도구"""
    pass


@cli.command()
@click.option('--refresh', '-r', is_flag=True, help='캐시 무시하고 새로고침')
def quota(refresh):
    """계정 쿼터 상태 조회"""
    service = get_quota_service()
    quotas = service.get_quota(force_refresh=refresh)
    
    if not quotas:
        click.echo("쿼터 정보를 가져올 수 없습니다.")
        return
    
    output = QuotaModel.format_cli_output(quotas)
    click.echo(output)


if __name__ == '__main__':
    cli()