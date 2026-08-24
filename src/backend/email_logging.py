import pathlib
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
import jinja2
from markdownify import markdownify

from bot_framework.yaml_wrapper import yaml


@dataclass
class EmailConfig:
    mail_server: str
    from_addr: str
    recipients: list[str]


def _load_config():
    config_file = pathlib.Path(f'config/email.yml')
    if config_file.exists():
        with config_file.open(mode='r', encoding='utf8') as y:
            config = dict(yaml.load(y))
    return EmailConfig(
        mail_server=config['mail_server'],
        recipients=config['recipients'],
        from_addr=config.get('from', 'Gyrobot <gyrobot@terrasoft.gr>')
    )


def send_email_log(template_name, **kwargs):
    cfg = _load_config()
    mail_server = cfg.mail_server

    template_loader = jinja2.FileSystemLoader(searchpath="email_templates")
    template_env = jinja2.Environment(loader=template_loader)
    if not template_name.endswith('.html'):
        template_name += '.html'
    template = template_env.get_template(template_name)
    html_part = template.render(**kwargs)

    msg = EmailMessage()
    msg['Subject'] = kwargs.get('subject', 'Eurobot Automated Email')
    msg['From'] = kwargs.get('from', cfg.from_addr)
    msg['To'] = kwargs.get('to', cfg.recipients)
    if 'cc' in kwargs:
        msg['cc'] = kwargs['cc']
    if 'bcc' in kwargs:
        msg['bcc'] = kwargs['bcc']

    msg.set_content(markdownify(html_part), subtype="plain")
    msg.add_alternative(html_part, subtype="html")


    s = smtplib.SMTP(mail_server)
    s.send_message(msg)
    s.quit()
