"""Bounded public HTTPS text retrieval for primary-source inspection."""
import ipaddress
import socket
import http.client
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from .search import SearchError
from .live import _RejectRedirects

class _Text(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','nav','footer','header'}:self.skip+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','nav','footer','header'} and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())


def read_source(url, *, opener=None, resolver=socket.getaddrinfo):
    try:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError()
        addresses=resolver(parsed.hostname,443,type=socket.SOCK_STREAM)
        # This workstation's outbound proxy uses fake DNS in 198.18/15 for public
        # hostnames. Do not confuse that transport address with a local origin.
        try:
            ipaddress.ip_address(parsed.hostname)
            literal=True
        except ValueError:literal=False
        def allowed(address):
            ip=ipaddress.ip_address(address)
            proxy_dns=not literal and ip.version==4 and ip in ipaddress.ip_network('198.18.0.0/15')
            return (ip.is_global and not ip.is_multicast) or proxy_dns
        if not addresses or any(not allowed(item[4][0]) for item in addresses):raise ValueError()
    except (ValueError,OSError):
        raise SearchError('source_url','只能读取公开HTTPS文本来源') from None
    active=opener or urllib.request.build_opener(_RejectRedirects())
    request=urllib.request.Request(url,headers={'Accept':'text/html,text/plain','User-Agent':'dojo-research-poc/1.0'})
    try:
        with active.open(request,timeout=20) as response:
            media=response.headers.get_content_type()
            if media not in {'text/html','text/plain','application/xhtml+xml'}:
                raise SearchError('source_type','来源不是HTML或纯文本；未读取PDF/二进制正文')
            raw=response.read(256001)
            body_truncated=len(raw)>256000
            raw=raw[:256000]
            text=raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
    except urllib.error.HTTPError as exc:
        status=exc.code;exc.close()
        raise SearchError('source_http_'+str(status),'来源HTTP读取失败') from None
    except (OSError,urllib.error.URLError,LookupError,http.client.HTTPException):
        raise SearchError('source_connect','无法读取来源正文') from None
    if media!='text/plain':
        parser=_Text();parser.feed(text);text='\n'.join(parser.parts)
    return {'url':url,'text':text[:20000],'truncated':body_truncated or len(text)>20000,
        'scope':'实际取得的来源文本，仍为外部主张；可能非全文，不代表独立复现'}
