"""GitHub signal collector."""

import time
from typing import List, Tuple, Optional

import requests

from .base import BaseCollector, CollectedSignal

API_BASE = "https://api.github.com"
RATE_LIMIT_SLEEP = 0.3


class GitHubCollector(BaseCollector):
    """Collects signals from GitHub API."""

    def _headers(self, token: Optional[str] = None):
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def _get(self, url: str, token: Optional[str] = None, params: dict = None):
        """Rate-limited GET request."""
        time.sleep(RATE_LIMIT_SLEEP)
        resp = requests.get(url, headers=self._headers(token), params=params or {})
        return resp

    def discover(self, org: str, token: Optional[str] = None) -> List[Tuple[str, str]]:
        """Discover GitHub users from an org's repositories.

        Fetches all repos for the org, then all contributors for each repo.
        Skips bots (login containing [bot]).

        Returns:
            List of ("github", username) tuples (deduplicated)
        """
        seen = set()
        results = []

        # Get org repos
        page = 1
        while True:
            resp = self._get(
                f"{API_BASE}/orgs/{org}/repos",
                token=token,
                params={"per_page": 100, "page": page, "type": "sources"}
            )
            if resp.status_code != 200:
                break
            repos = resp.json()
            if not repos:
                break

            for repo in repos:
                if repo.get("fork"):
                    continue
                repo_name = repo["name"]

                # Get contributors for this repo
                contrib_resp = self._get(
                    f"{API_BASE}/repos/{org}/{repo_name}/contributors",
                    token=token,
                    params={"per_page": 100}
                )
                if contrib_resp.status_code != 200:
                    continue

                for contributor in contrib_resp.json():
                    login = contributor.get("login", "")
                    ctype = contributor.get("type", "")

                    # Skip bots
                    if "[bot]" in login or ctype == "Bot":
                        continue

                    if login not in seen:
                        seen.add(login)
                        results.append(("github", login))

            page += 1

        return results

    def collect(self, identifier_value: str, contact_id: str,
                token: Optional[str] = None) -> List[CollectedSignal]:
        """Collect signals for a GitHub user.

        Produces:
        - github/profile signal: bio, company, location, public_repos, followers
        - github/commit signals: per-repo commit count

        Returns:
            List of CollectedSignal objects
        """
        signals = []

        # Profile signal
        profile_resp = self._get(
            f"{API_BASE}/users/{identifier_value}",
            token=token
        )
        if profile_resp.status_code == 200:
            profile = profile_resp.json()
            payload = {
                "login": profile.get("login"),
                "bio": profile.get("bio"),
                "company": profile.get("company"),
                "location": profile.get("location"),
                "public_repos": profile.get("public_repos"),
                "followers": profile.get("followers"),
                "created_at": profile.get("created_at"),
            }
            signals.append(CollectedSignal(
                source="github",
                signal_type="github/profile",
                payload=payload,
                source_event_id=f"github:user:{identifier_value}",
                evidence_note=f"GitHub profile for {identifier_value}",
            ))

        # Commit signals per repo
        repos_resp = self._get(
            f"{API_BASE}/users/{identifier_value}/repos",
            token=token,
            params={"per_page": 100, "sort": "updated"}
        )
        if repos_resp.status_code == 200:
            repos = repos_resp.json()
            for repo in repos:
                if repo.get("fork"):
                    continue

                repo_full = repo.get("full_name", "")
                repo_name = repo.get("name", "")

                # Get commit count via search API
                search_resp = self._get(
                    f"{API_BASE}/search/commits",
                    token=token,
                    params={"q": f"author:{identifier_value} repo:{repo_full}"}
                )

                commit_count = 0
                if search_resp.status_code == 200:
                    commit_count = search_resp.json().get("total_count", 0)

                if commit_count > 0:
                    payload = {
                        "repo": repo_full,
                        "repo_name": repo_name,
                        "commit_count": commit_count,
                        "stars": repo.get("stargazers_count", 0),
                        "language": repo.get("language"),
                    }
                    signals.append(CollectedSignal(
                        source="github",
                        signal_type="github/commit",
                        payload=payload,
                        source_event_id=f"github:commits:{repo_full}:{identifier_value}",
                        evidence_note=f"{commit_count} commits in {repo_full}",
                    ))

        return signals
