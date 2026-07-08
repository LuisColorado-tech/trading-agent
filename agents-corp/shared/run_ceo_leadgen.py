import sys, time
sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
from shared.ceo_supervisor import LeadGen_CEO
ceo = LeadGen_CEO()
ceo.log('CEO online — supervising leadgen')
while True:
    try:
        ceo.cycles = getattr(ceo, 'cycles', 0) + 1
        ceo.run_cycle()
        time.sleep(300)
    except KeyboardInterrupt: break
    except Exception as e:
        ceo.log(f'Error: {e}')
        time.sleep(60)
