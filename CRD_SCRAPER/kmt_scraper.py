import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
import pandas as pd
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
    extraction_method: str  

class KMTScraperPro:
    BASE_URL = "https://kmt.vander-lingen.nl"

    def __init__(self, doi: str = "10.1021/jacsau.4c01276"):
        self.doi = doi
        self.session = self._init_session()
        self.collected_reactions: List[ReactionData] = []
        self.seen_smiles = set()

    def _init_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        })
        return session

    def _parse_smiles_string(self, smiles: str) -> Optional[dict]:
        """Splits a reaction SMILES into its components."""
        try:
            
            if ">>" in smiles:
                parts = smiles.split(">>")
                reactants = parts[0].split(".")
                reagents = []
                products = parts[1].split(".")
            elif ">" in smiles:
                parts = smiles.split(">")
                reactants = parts[0].split(".")
                reagents = parts[1].split(".")
                products = parts[2].split(".")
            else:
                return None

            return {
                "reactants": [s for s in reactants if s],
                "reagents": [s for s in reagents if s],
                "products": [s for s in products if s],
            }
        except Exception:
            return None

    def _extract_all_potential_smiles(self, soup: BeautifulSoup, html: str) -> List[tuple]:
        """Multimodal extraction: attributes, JS, and raw text patterns."""
        found = []

        
        for el in soup.find_all(attrs={"data-reaction-smiles": True}):
            found.append((el.get("data-reaction-smiles"), "data-attr"))

       
        js_patterns = [
            r"['\"]([A-Za-z0-9\[\]()=#@+\-\\/.>]+>>?[A-Za-z0-9\[\]()=#@+\-\\/.>]+)['\"]",
        ]
        for pattern in js_patterns:
            matches = re.findall(pattern, html)
            for m in matches:
                if ">" in m and len(m) > 5:
                    found.append((m, "js-regex"))
        
        return found

    def scrape(self, max_pages: int = 5):
        current_url = f"{self.BASE_URL}/data/reaction/doi/{self.doi}/start/0"
        
        for i in range(max_pages):
            print(f"--- Processing Page {i+1} | {current_url} ---")
            
            response = self.session.get(current_url, timeout=20)
            if response.status_code != 200:
                break
                
            soup = BeautifulSoup(response.text, "html.parser")
            raw_data = self._extract_all_potential_smiles(soup, response.text)
            
            new_count = 0
            for smiles, method in raw_data:
                if smiles not in self.seen_smiles:
                    parsed = self._parse_smiles_string(smiles)
                    if parsed:
                        self.collected_reactions.append(ReactionData(
                            reaction_smiles=smiles,
                            reactant_smiles=parsed["reactants"],
                            reagent_smiles=parsed["reagents"],
                            product_smiles=parsed["products"],
                            source_url=current_url,
                            scraped_at=datetime.now().isoformat(),
                            extraction_method=method
                        ))
                        self.seen_smiles.add(smiles)
                        new_count += 1
            
            print(f"Found {new_count} new reactions.")

            
            next_link = soup.find("a", string=re.compile(r"Next", re.I))
            if next_link and next_link.get("href"):
                href = next_link["href"]
                current_url = href if href.startswith("http") else self.BASE_URL + href
            else:
                
                start_val = (i + 1) * 10
                current_url = f"{self.BASE_URL}/data/reaction/doi/{self.doi}/start/{start_val}"

            time.sleep(random.uniform(1.0, 2.5))

    def save_results(self, filename: str):
        """Saves to both JSON and CSV for convenience."""
        dicts = [asdict(r) for r in self.collected_reactions]
        
        
        with open(f"{filename}.json", "w") as f:
            json.dump(dicts, f, indent=2)
            
        
        df = pd.DataFrame(dicts)
        df.to_csv(f"{filename}.csv", index=False)
        print(f"Success! Saved {len(df)} reactions to {filename}.json and {filename}.csv")

if __name__ == "__main__":
    
    scraper = KMTScraperPro(doi="10.1021/jacsau.4c01276")
    scraper.scrape(max_pages=3) 
    scraper.save_results("kmt_data_export")