"""Apollo company and decision-maker discovery.

Apollo's People API Search intentionally does not return email addresses, so this
module never claims an email. Emails are discovered separately through Hunter.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from ..config import Config, ConfigError
from ..http import ProviderError, Transport, request, require_ok
from ..normalize import normalize_company, normalize_domain
from ..util import now_iso, stable_id


class ApolloClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.apollo.io/api/v1",
        transport: Optional[Transport] = None,
        timeout: int = 45,
        pause: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise ConfigError("APOLLO_API_KEY is missing.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self.pause = max(0.0, pause)
        self.sleep = sleep

    def _post(self, path: str, payload: Dict[str, Any], action: str) -> Dict[str, Any]:
        response = request(
            "POST",
            f"{self.base_url}/{path.lstrip('/')}",
            provider="apollo",
            headers={"x-api-key": self.api_key, "Cache-Control": "no-cache"},
            json_body=payload,
            timeout=self.timeout,
            retries=2,
            transport=self.transport,
        )
        data = require_ok(response, "apollo", action)
        return data if isinstance(data, dict) else {}

    def search_companies(
        self,
        keyword_tags: Sequence[str],
        locations: Sequence[str] = (),
        employee_ranges: Sequence[str] = (),
        page: int = 1,
        per_page: int = 25,
        organization_names: Sequence[str] = (),
    ) -> List[Dict[str, Any]]:
        """Search Apollo's organisation database. Costs zero credits on current plans."""
        payload: Dict[str, Any] = {"page": max(1, int(page)), "per_page": max(1, min(100, int(per_page)))}
        if keyword_tags:
            payload["q_organization_keyword_tags"] = list(keyword_tags)
        if locations:
            payload["organization_locations"] = list(locations)
        if employee_ranges:
            payload["organization_num_employees_ranges"] = list(employee_ranges)
        if organization_names:
            payload["q_organization_name"] = " ".join(organization_names)
        data = self._post("mixed_companies/search", payload, "company search")
        organizations = data.get("organizations") or data.get("accounts") or []
        if self.pause:
            self.sleep(self.pause)
        return [org for org in organizations if isinstance(org, dict)]

    def search_people(
        self,
        domains: Sequence[str],
        titles: Sequence[str] = (),
        locations: Sequence[str] = (),
        page: int = 1,
        per_page: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find named decision makers (no email addresses are returned by Apollo)."""
        payload: Dict[str, Any] = {"page": max(1, int(page)), "per_page": max(1, min(100, int(per_page)))}
        if domains:
            payload["q_organization_domains_list"] = list(domains)
        if titles:
            payload["person_titles"] = list(titles)
        if locations:
            payload["person_locations"] = list(locations)
        data = self._post("mixed_people/api_search", payload, "people search")
        people = data.get("people") or data.get("contacts") or []
        if self.pause:
            self.sleep(self.pause)
        return [person for person in people if isinstance(person, dict)]

    # ------------------------------------------------------------------ mapping

    def company_to_lead(self, organization: Dict[str, Any]) -> Optional[Dict[str, str]]:
        name = str(organization.get("name") or organization.get("organization_name") or "").strip()
        domain = normalize_domain(
            organization.get("primary_domain")
            or organization.get("domain")
            or organization.get("website_url")
        )
        if not name and not domain:
            return None
        website = str(organization.get("website_url") or (f"https://{domain}" if domain else "")).strip()
        country = str(organization.get("country") or organization.get("organization_country") or "").strip()
        industry = str(organization.get("industry") or organization.get("industry_tag_name") or "").strip()
        employees = organization.get("estimated_num_employees") or organization.get("num_employees")
        employee_range = "unknown"
        if isinstance(employees, (int, float)) and employees > 0:
            employee_range = _employee_bucket(int(employees))
        elif organization.get("organization_num_employees_ranges"):
            ranges = organization.get("organization_num_employees_ranges")
            employee_range = str(ranges[0] if isinstance(ranges, list) and ranges else ranges)
        timestamp = now_iso()
        lead_id = stable_id("apollo", domain or name, country)
        return {
            "lead_id": lead_id,
            "company_name": name,
            "normalized_company": normalize_company(name),
            "domain": domain,
            "website": website,
            "country": country,
            "industry": industry,
            "employee_range": employee_range,
            "contact_name": "",
            "contact_title": "",
            "email": "",
            "email_type": "",
            "email_status": "unverified",
            "email_score": "0",
            "email_verified_at": "",
            "email_source": "",
            "phone_business": "",
            "phone_source": "",
            "phone_type": "",
            "source_provider": "apollo",
            "source_url": website or (f"https://{domain}" if domain else ""),
            "source_ref": str(organization.get("id") or ""),
            "service_fit": "",
            "qualification_score": "0",
            "qualification_status": "pending",
            "qualification_reason": "",
            "need_summary": "",
            "priority": "",
            "outreach_status": "not_contacted",
            "follow_up_count": "0",
            "last_contact_at": "",
            "last_reply_at": "",
            "order_status": "none",
            "whatsapp_status": "",
            "do_not_contact": "false",
            "consent_basis": "",
            "notes": "Company record from Apollo; business need and email are not yet verified.",
            "created_at": timestamp,
            "updated_at": timestamp,
        }

    def people_to_contacts(self, people: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Extract contact names/titles/linkedin only. No email is inferred."""
        contacts = []
        for person in people:
            name = " ".join(
                part
                for part in [
                    str(person.get("first_name") or "").strip(),
                    str(person.get("last_name") or person.get("last_name_obfuscated") or "").strip(),
                ]
                if part
            ).strip()
            if not name:
                continue
            contacts.append(
                {
                    "name": name,
                    "title": str(person.get("title") or "").strip(),
                    "linkedin": str(person.get("linkedin_url") or "").strip(),
                    "organization_domain": normalize_domain(
                        (person.get("organization") or {}).get("primary_domain")
                        or (person.get("organization") or {}).get("website_url")
                    ),
                    "apollo_id": str(person.get("id") or ""),
                }
            )
        return contacts


def _employee_bucket(count: int) -> str:
    for low, high in ((1, 10), (11, 50), (51, 200), (201, 500), (501, 1000), (1001, 5000), (5001, 10000)):
        if low <= count <= high:
            return f"{low}-{high}"
    return "10001+"


def client_from_config(config: Config, transport: Optional[Transport] = None) -> ApolloClient:
    return ApolloClient(
        config.apollo_api_key,
        base_url=config.apollo_base_url,
        transport=transport,
        timeout=config.request_timeout,
        pause=config.request_pause,
    )
