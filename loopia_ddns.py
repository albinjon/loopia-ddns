import requests
import os
from dotenv import load_dotenv
import time
from typing import cast, List, Dict, Union
from datetime import datetime
import logging
import xmlrpc.client
from typing import List, Dict

class LoopiaUpdater:
    current_ips: Dict[str, str | None]
    zone_record_ids: Dict[str, str | None]
    def __init__(self, username: str, password: str, domain: str, subdomains: List[str]):
        """
        Initialize the Loopia DNS record updater
        
        Args:
            username: Loopia API username
            password: Loopia API password
            domain: Main domain name
            subdomains: List of subdomains to update (use '@' for root domain)
            customer_number: Optional customer number for resellers
        """
        self.username = username
        self.password = password
        self.domain = domain
        self.subdomains = subdomains
        self.api_url = 'https://api.loopia.se/RPCSERV'
        self.current_ips = {subdomain: None for subdomain in subdomains}
        self.zone_record_ids = {subdomain: None for subdomain in subdomains}
        
        logging.basicConfig(
            filename='loopia_ddns.log',
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
        if not subdomains:
            raise ValueError("At least one subdomain must be provided")

    def get_public_ip(self) -> str:
        """Get the current public IP using multiple IP detection services for reliability"""
        ip_services = [
            'https://api.ipify.org?format=json',
            'https://api.ip.sb/jsonip',
            'https://api64.ipify.org?format=json'
        ]
        
        for service in ip_services:
            try:
                response = requests.get(service, timeout=10)
                if response.status_code == 200:
                    return response.json()['ip']
            except Exception as e:
                logging.warning(f"Failed to get IP from {service}: {str(e)}")
                continue
                
        raise Exception("Failed to get public IP from all services")

    def update_dns_record(self, subdomain: str, new_ip: str) -> bool:
        """
        Update the A record for a specific subdomain
        
        Args:
            subdomain: The subdomain to update
            new_ip: The new IP address to set
            
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            client = xmlrpc.client.ServerProxy(uri = self.api_url, encoding='utf-8')

            record_id = 0
            params: List[Union[str, dict]] = [
                self.username,
                self.password,
                self.domain,
                subdomain,
            ]

            cached_zone_record_id = self.zone_record_ids[subdomain] or 0
            if cached_zone_record_id == 0:
                response = cast(List[Dict[str, str]], client.getZoneRecords(*params))
                existing_dns_record = len(response) > 0
                if existing_dns_record:
                    record_id = self.zone_record_ids[subdomain] = response[0].get('record_id')
            else:
                record_id = cached_zone_record_id

            record_obj = {
                'type': 'A',           # A record for IPv4
                'ttl': 300,            # 5 minutes TTL for frequent updates
                'priority': 0,         # Not used for A records
                'rdata': new_ip,       # The new IP address
                'record_id': record_id # 0 for new records, but when we already have a record, we want 
                                       # to update it.
            }

            params.append(record_obj)
            status = client.updateZoneRecord(*params)

            if status == 'OK':
                self.current_ips[subdomain] = new_ip
                logging.info(f"Successfully updated DNS record for {subdomain}.{self.domain} to {new_ip}")
                return True
            else:
                logging.error(f"Failed to update DNS record for {subdomain}.{self.domain}. Status: {status}")
                return False
                
        except Exception as e:
            logging.error(f"Error updating DNS record for {subdomain}.{self.domain}: {str(e)}")
            return False

    def update_all_records(self) -> Dict[str, bool]:
        """
        Update all configured subdomains if needed
        
        Returns:
            Dict[str, bool]: Dictionary of subdomain to success status
        """
        try:
            new_ip = self.get_public_ip()
            results = {}
            
            for subdomain in self.subdomains:
                if new_ip != self.current_ips[subdomain]:
                    results[subdomain] = self.update_dns_record(subdomain, new_ip)
                    if results[subdomain]:
                        logging.info(f"Updated {subdomain}.{self.domain} to {new_ip} at {datetime.now()}")
                else:
                    logging.info(f"No IP change needed for {subdomain}.{self.domain}")
                    results[subdomain] = True
                    
            return results
            
        except Exception as e:
            logging.error(f"Failed to update records: {str(e)}")
            return {subdomain: False for subdomain in self.subdomains}

def main():
    load_dotenv()
    username=os.getenv('USERNAME')
    password=os.getenv('PASSWORD')
    domain=os.getenv('DOMAIN')
    # Comma separated list of subdomains
    subdomains=os.getenv('SUBDOMAINS')
    seconds_interval=os.getenv('UPDATE_INTERVAL')
    if(not (username and password and domain and subdomains and seconds_interval)):
        raise Exception('Missing required environment variables')
    split_sub = subdomains.split(',')

    updater = LoopiaUpdater(
        username,
        password,
        domain,
        subdomains=split_sub,
    )
    
    logging.info(f"Starting DNS updater for {domain} subdomains: {', '.join(split_sub)}")
    while True:
        try:
            results = updater.update_all_records()
            failed = [sub for sub, success in results.items() if not success]
            if failed:
                logging.warning(f"Failed to update some subdomains: {', '.join(failed)}")
        except Exception as e:
            logging.error(f"Update cycle failed: {str(e)}")
        
        time.sleep(int(seconds_interval))

if __name__ == "__main__":
    main()
