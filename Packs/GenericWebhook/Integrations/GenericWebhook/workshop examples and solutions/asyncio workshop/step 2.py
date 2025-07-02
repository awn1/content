import aiohttp
import asyncio



async def send_post_request_async(endpoint):
    url = "https://edl-crtx-cntnt-ownr-xsiam-shahaf-6606.xdr-qa2-uat.us.paloaltonetworks.com/xsoar/instance/execute/Generic_Webhook_instance_2/"
    headers = {
        'Authorization': 'Basic YTph',
        'Content-Type': 'application/json' # Important: ensure this header is set
    }
    payload = {
        "payload": {
            "name": "yuval"
        }
    }
    async with aiohttp.ClientSession(base_url=url, headers=headers) as session:
        try:
            async with session.post(url=endpoint, json=payload) as response:
                response.raise_for_status()  # Check for any HTTP errors
                raw_response = await response.text()
                print(f"Request to {url}{endpoint} successful! Response: {raw_response}")
                return raw_response
        except aiohttp.ClientError as e:
            print(f"An aiohttp client error occurred: {e}")
            if 'response' in locals() and response is not None:
                try:
                    error_content = await response.text()
                    print(f"Error Response Content: {error_content}")
                except Exception as text_e:
                    print(f"Could not read error response text: {text_e}")
            return ''
        except Exception as e:
            print(f"An unexpected error occurred during POST: {e}")
            return ''


async def send_get_request_async(endpoint):
    url = "https://edl-crtx-cntnt-ownr-xsiam-shahaf-6606.xdr-qa2-uat.us.paloaltonetworks.com/xsoar/instance/execute/Generic_Webhook_instance_2/"
    headers = {
    'Authorization': 'Basic YTph',
    }
    params = {"name": "yuval"}
    async with aiohttp.ClientSession(base_url=url, headers=headers) as session, session.get(url=endpoint, params=params) as response:
        try:
            response.raise_for_status()  # Check for any HTTP errors
            raw_response = await response.text()
            return raw_response
        except aiohttp.ClientError as e:
            print(e)
            raw_response = ''
    print(raw_response)
    return raw_response


async def main():
    tasks = [asyncio.create_task(send_post_request_async("step_2"))]
    await asyncio.sleep(3)
    tasks.append(asyncio.create_task(send_get_request_async("step_2_completion_attempt")))
    results = await asyncio.gather(*tasks)
    for result in results:
        print(result)

asyncio.run(main())