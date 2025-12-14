import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime


@dataclass
class ReactionData:
    reaction_smiles: str
    reactant_smiles: List[str]
    reagent_smiles: List[str]
    product_smiles: List[str]
    source_url: str
    scraped_at: str


class KMTScraper:
    BASE_URL = "https://kmt.vander-lingen.nl"
    
    def __init__(self, doi: str = "10.1021/jacsau.4c01276"):
        self.doi = doi
        self.session = self._init_session()
        self.collected_reactions: List[ReactionData] = []
    
    def _init_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        return session
    
    def _build_url(self, start: int = 0) -> str:
        return f"{self.BASE_URL}/data/reaction/doi/{self.doi}/start/{start}"
    
    def _fetch_page(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def _parse_smiles_string(self, smiles: str) -> dict:
        parts = smiles.split(">")
        
        if len(parts) < 3:
            parts = smiles.split(">>")
            if len(parts) == 2:
                parts = [parts[0], "", parts[1]]
            else:
                return None
        
        reactants = [s.strip() for s in parts[0].split(".") if s.strip()]
        reagents = [s.strip() for s in parts[1].split(".") if s.strip()] if len(parts) > 1 else []
        products = [s.strip() for s in parts[2].split(".") if s.strip()] if len(parts) > 2 else []
        
        return {
            "reactants": reactants,
            "reagents": reagents,
            "products": products
        }
    
    def _extract_from_data_attributes(self, soup: BeautifulSoup) -> List[str]:
        smiles_list = []
        for element in soup.find_all(attrs={"data-reaction-smiles": True}):
            smiles = element.get("data-reaction-smiles")
            if smiles and smiles.strip():
                smiles_list.append(smiles.strip())
        return smiles_list
    
    def _extract_from_javascript(self, html: str) -> List[str]:
        smiles_list = []
        
        patterns = [
            r"reactions\.push\(\s*['\"]([^'\"]+)['\"]\s*\)",
            r"reaction[Ss]miles\s*[=:]\s*['\"]([^'\"]+)['\"]",
            r"data-reaction-smiles\s*=\s*['\"]([^'\"]+)['\"]",
            r"smiles\s*:\s*['\"]([^'\"]+>>?[^'\"]+)['\"]",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html)
            for match in matches:
                if ">" in match:
                    smiles_list.append(match)
        
        return smiles_list
    
    def _extract_from_tables(self, soup: BeautifulSoup) -> List[str]:
        smiles_list = []
        
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if ">" in text and "." in text:
                        if re.match(r'^[A-Za-z0-9\[\]()=#@+\-\\/.>]+$', text):
                            smiles_list.append(text)
        
        return smiles_list
    
    def _find_next_page_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        next_indicators = ["next", "»", ">", "→", "forward"]
        
        for link in soup.find_all("a", href=True):
            link_text = link.get_text(strip=True).lower()
            if any(indicator in link_text for indicator in next_indicators):
                href = link.get("href")
                if href:
                    if href.startswith("http"):
                        return href
                    else:
                        return f"{self.BASE_URL}{href}" if href.startswith("/") else f"{self.BASE_URL}/{href}"
        
        match = re.search(r"/start/(\d+)", current_url)
        if match:
            current_start = int(match.group(1))
            next_start = current_start + 10
            return self._build_url(next_start)
        
        return None
    
    def _process_page(self, html: str, url: str) -> List[ReactionData]:
        soup = BeautifulSoup(html, "html.parser")
        all_smiles = set()
        
        all_smiles.update(self._extract_from_data_attributes(soup))
        all_smiles.update(self._extract_from_javascript(html))
        all_smiles.update(self._extract_from_tables(soup))
        
        reactions = []
        timestamp = datetime.now().isoformat()
        
        for smiles in all_smiles:
            parsed = self._parse_smiles_string(smiles)
            if parsed and parsed["products"]:
                reaction = ReactionData(
                    reaction_smiles=smiles,
                    reactant_smiles=parsed["reactants"],
                    reagent_smiles=parsed["reagents"],
                    product_smiles=parsed["products"],
                    source_url=url,
                    scraped_at=timestamp
                )
                reactions.append(reaction)
        
        return reactions
    
    def scrape(self, max_pages: int = 20, delay_range: tuple = (0.5, 1.5)) -> List[ReactionData]:
        print(f"Starting scrape for DOI: {self.doi}")
        print(f"Max pages: {max_pages}")
        print("-" * 50)
        
        current_url = self._build_url(0)
        pages_scraped = 0
        seen_urls = set()
        
        while current_url and pages_scraped < max_pages:
            if current_url in seen_urls:
                print(f"Already visited {current_url}, stopping to avoid loop")
                break
            
            seen_urls.add(current_url)
            print(f"Scraping page {pages_scraped + 1}: {current_url}")
            
            html = self._fetch_page(current_url)
            if not html:
                print(f"Failed to fetch page, stopping")
                break
            
            reactions = self._process_page(html, current_url)
            new_count = 0
            
            for reaction in reactions:
                if reaction.reaction_smiles not in [r.reaction_smiles for r in self.collected_reactions]:
                    self.collected_reactions.append(reaction)
                    new_count += 1
            
            print(f"  Found {len(reactions)} reactions, {new_count} new")
            
            if new_count == 0 and pages_scraped > 0:
                print("  No new reactions found, checking next page...")
            
            soup = BeautifulSoup(html, "html.parser")
            current_url = self._find_next_page_url(soup, current_url)
            pages_scraped += 1
            
            if current_url:
                delay = random.uniform(*delay_range)
                time.sleep(delay)
        
        print("-" * 50)
        print(f"Scraping complete. Total reactions: {len(self.collected_reactions)}")
        
        return self.collected_reactions
    
    def to_json(self, filepath: str = None) -> str:
        data = {
            "metadata": {
                "doi": self.doi,
                "total_reactions": len(self.collected_reactions),
                "scraped_at": datetime.now().isoformat(),
                "source": self.BASE_URL
            },
            "reactions": [asdict(r) for r in self.collected_reactions]
        }
        
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        
        if filepath:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"Data saved to {filepath}")
        
        return json_str
    
    def get_summary(self) -> dict:
        all_reactants = set()
        all_products = set()
        
        for r in self.collected_reactions:
            all_reactants.update(r.reactant_smiles)
            all_products.update(r.product_smiles)
        
        return {
            "total_reactions": len(self.collected_reactions),
            "unique_reactants": len(all_reactants),
            "unique_products": len(all_products),
            "doi": self.doi
        }


def main():
    scraper = KMTScraper(doi="10.1021/jacsau.4c01276")
    
    reactions = scraper.scrape(max_pages=10, delay_range=(0.8, 1.5))
    
    print("\nSummary:")
    summary = scraper.get_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    output_file = "kmt_reactions.json"
    scraper.to_json(output_file)
    
    if reactions:
        print("\nSample reaction:")
        sample = reactions[0]
        print(f"  Full SMILES: {sample.reaction_smiles[:80]}...")
        print(f"  Reactants: {sample.reactant_smiles}")
        print(f"  Products: {sample.product_smiles}")


if __name__ == "__main__":
    main()




