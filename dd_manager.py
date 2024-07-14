import logging
import typing
import json
import requests
import dateutil.parser
import datetime
import random
import argparse


TOKEN = '2498368948699325b02ee94a5180bcbf37cdab49'

class DD:
    LAST_REVIEWED = 2

    def __init__(self, token: str, start_date=None, end_date=None):
        """
        Initialize the object with the provided domain and token.

        :param domain: The domain for the object.
        :param token: The token for authentication.

        :raises ValueError: If the token or domain is None or an empty string.
        """
        self._read_tasks_file()

        self._domain = "dd.codescoring.tech"
        
        if token is None or token == "":
            raise ValueError("Token cannot be None")

        self._headers = {
            'content-type': 'application/json',
            'Authorization': f'Token {token}'
        }

        if start_date == None:
            # get last week day
            self._start_date = datetime.date.today() - datetime.timedelta(days=7)
        else:
            self._start_date = datetime.datetime.strptime(start_date, '%d/%m/%Y').date()

        if end_date == None:
            # get today
            self._end_date = datetime.date.today()
        else:
            self._end_date = datetime.datetime.strptime(end_date, '%d/%m/%Y').date()

    def _read_tasks_file(self):
        """
        Reads tasks from tasks.json file and assign it to users
        """

        with open('tasks.json', 'r', encoding='utf-8') as f:
            self.users = json.load(f)
        
    def _write_tasks_file(self):
        """
        Writes tasks from users to tasks.json
        """

        with open('tasks.json', 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=4)

    def _send_request(self, url: str, params=None) -> typing.Any:
        """
        A function that sends a GET request to a specified URL with optional parameters.

        :param url: The URL to send the GET request to.
        :param params: The parameters to include in the request. Defaults to None.

        :raises Exception: If an exception occurs during the request.

        :return: The JSON response from the GET request or None if an exception occurs.
        """

        if params is None:
            params = {}

        try:
            response = requests.get(url, headers=self._headers, params=params).json()
        except Exception as e:
            logging.error(e)
            return None

        return response

    def get_statistic(self, save=False, verbose=False):
        self._get_findings()
        self._calculate_debts()
        self._print_results(verbose)

        if save:
            # saves the result
            self._clean_stats()
            self._write_tasks_file()

    def _clean_stats(self):
        # delete unused values in stats
        for user in self.users.values():
            user["task_closed"] = 0
            user["closed"] = 0
            user["risk_accepted"] = 0

    def _get_findings(self, limit=210, offset=0) -> typing.List[typing.Dict[str, typing.Any]]:
        params = {
            'o': '-last_status_update',
            'active': 'false',
            'limit': limit,
            'offset': offset
        }

        findings_temp = self._send_request(f"https://{self._domain}/api/v2/findings/", params)
        for finding in findings_temp["results"]:
            if finding["is_mitigated"]:
                # closed finding

                mitigated_date = dateutil.parser.isoparse(finding["mitigated"]).date()
                # check that accepted date in the interval
                if (self._end_date < mitigated_date):
                    continue
                if (mitigated_date < self._start_date):
                    return

                user_id = finding["mitigated_by"]
                self._close_task(str(user_id), finding["id"], "closed")

            elif finding["risk_accepted"]:
                # risk acceptance
                risk_acceptance = finding["accepted_risks"][0]
                if len(finding["accepted_risks"]) > 1:
                    # TODO handle that better, because we only take the first risk acceptance
                    # more than one risk acceptance. Bad
                    print("\nSEVERAL RISK ACCEPTANCE: finding: {}\n".format(finding["id"]))

                accepted_datetime = dateutil.parser.isoparse(risk_acceptance["created"])
                if (self._end_date < accepted_datetime.date()):
                    continue
                if (accepted_datetime.date() < self._start_date):
                    if (accepted_datetime != dateutil.parser.isoparse(risk_acceptance["updated"])):
                        # it was updated, keep going
                        continue

                    return

                user_id = risk_acceptance["owner"]
                self._close_task(str(user_id), finding["id"], "risk_accepted")

        if findings_temp["next"]:
            self._get_findings(25, offset + limit)

    def _close_task(self, user_id, finding_id, finding_type="closed"):
        try:
            user = self.users[user_id]
        except KeyError:
            print("unknown user id: {}".format(user_id))
            return

        user[finding_type] += 1

        if (finding_id in user["tasks"]):
            user["task_closed"] += 1
            # now in tasks we only have debts
            user["tasks"].remove(finding_id)

    def _calculate_debts(self):
        for user in self.users.values():
            user["debt"] += user["norm"] - (user["closed"] + user["risk_accepted"])

    def _print_results(self, verbose=False):
        for user in self.users.values():
            output = "{name}: {task_closed}/{norm}".format(name=user["name"], task_closed=user["risk_accepted"]+user["closed"], norm=user["norm"])
            if verbose:
                verbose_statistic = "\tпринятых: {accepted}\tзакрытых: {closed}\tвыделенных: {assigned}\tдолг: {debt}".format(\
                    accepted=user["risk_accepted"], closed=user["closed"], assigned=user["task_closed"], debt=user["debt"])
                output += verbose_statistic
            
            print(output)

    def _construct_url(self, id, dir="finding"):
        return "https://dd.codescoring.tech/{dir}/{id}".format(dir=dir, id=id)

    def assign_tasks(self, limit=250, save=False):
        params = {
            'has_tags': 'false',
            'active': 'true',
            'accepted': 'false',
            'limit': limit,
        }

        findings_temp = self._send_request(f"https://{self._domain}/api/v2/findings/", params)
        findings = findings_temp["results"]
        # check that we got expected number of findings
        if len(findings) != limit:
            print("not enough open findings: {}".format(len(findings)))

        # print tasks
        for user in self.users.values():
            print("\n-------")
            print(user["name"])
            # print debts first for a user
            for debt in user["tasks"]:
                print(self._construct_url(debt))

            for _ in range(user["norm"]):
                finding = random.choice(findings)
                finding_id = finding["id"]
                user["tasks"].append(finding_id)
                print(self._construct_url(finding_id))
                findings.remove(finding)
                
                if save:
                    # add tag "inwork" to the finding
                    requests.post("https://{domain}/api/v2/findings/{id}/tags/".format(domain=self._domain, id=finding_id),\
                         json={'tags': ['inwork']}, headers=self._headers)

        # write tasks to a file
        if save:
            self._write_tasks_file()

    def check_findings(self):
        # check that reactivate_expired is not set
        self._check_reactivate_expired()
        # check that no finding with risk acceptance is active
        self._check_active_risk_accepted()

    def _check_reactivate_expired(self, limit=100, offset=0):
        params = {
            'limit': limit,
            'offset': offset
        }
        findings_temp = self._send_request(f'https://{self._domain}/api/v2/risk_acceptance/', params=params)
        findings = findings_temp["results"]
        for finding in findings:
            if finding["reactivate_expired"]:
                if len(finding["accepted_findings"]) > 0:
                    print("reactivate_expired is true: " + self._construct_url(finding["accepted_findings"][0]))
                else:
                    print("not risk_accepted but reactivate_expired: " + self._construct_url(finding["id"]))

        if findings_temp["next"]:
            self._check_reactivate_expired(limit, offset + limit)

    def _check_active_risk_accepted(self, limit=100, offset=0):
        params = {
            'limit': limit,
            'offset': offset,
            'active': True
        }
        findings_temp = self._send_request(f'https://{self._domain}/api/v2/findings/', params=params)
        findings = findings_temp["results"]
        for finding in findings:
            if len(finding["accepted_risks"]) > 0:
                print("Active risk acceptance: " + self._construct_url(finding["id"]))

        if findings_temp["next"]:
            self._check_active_risk_accepted(limit, offset + limit)


def stats(args):
    dd_client = DD(token=(args.token if TOKEN=='' else TOKEN), start_date=args.start_date, end_date=args.end_date)
    dd_client.get_statistic(save=args.save, verbose=args.verbose)

def assign(args):
    dd_client = DD(token=(args.token if TOKEN=='' else TOKEN))
    dd_client.assign_tasks(save=args.save)

def check(args):
    dd_client = DD(token=(args.token if TOKEN=='' else TOKEN))
    dd_client.check_findings()

parser = argparse.ArgumentParser(description='Этот скрипт распределяет сработки по размечающим на неделю, а также собирает статистику разметки', add_help=True)
parser.add_argument('-t', '--token', required=TOKEN=='', help="Токен от платформы. Можно узнать: https://dd.codescoring.tech/api/key-v2")

subparsers = parser.add_subparsers(required=True)
stat_parser = subparsers.add_parser('stats', help='Собрать статистику за период')
stat_parser.add_argument('-d', '--start_date', help='(29/07/2002) - Начальная дата (включительно) после которой собрать статистику. По умолчанию - неделю назад')
stat_parser.add_argument('-e', '--end_date', help='(29/07/2002) - Конечная дата (включительно) для сбора статистики. По умолчанию - сегодняшний день')
stat_parser.add_argument('-v', '--verbose', action='store_true', help="Подробный вывод статистики")
stat_parser.add_argument('-s', '--save', action='store_true', help="Сохранить статистику в файл")
stat_parser.set_defaults(func=stats)

assign_parser = subparsers.add_parser('assign', help='Распределить открытые сработки на неделю')
assign_parser.add_argument('-s', '--save', action='store_true', help="Сохранить распределение в файл")
assign_parser.set_defaults(func=assign)

check_parser = subparsers.add_parser('check', help='Проверить сработки на валидность')
check_parser.set_defaults(func=check)

args = parser.parse_args()
args.func(args)