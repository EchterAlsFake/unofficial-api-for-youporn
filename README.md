<h1 align="center">YouPorn API</h1> 

<div align="center">
    <a href="https://pepy.tech/project/youporn_api"><img src="https://static.pepy.tech/badge/youporn_api" alt="Downloads"></a>
    <a href="https://github.com/EchterAlsFake/youporn_api/workflows/"><img src="https://github.com/EchterAlsFake/youporn_api/workflows/CodeQL/badge.svg" alt="CodeQL Analysis"/></a>
    <a href="https://echteralsfake.me/ci/youporn_api/badge.svg"><img src="https://echteralsfake.me/ci/youporn_api/badge.svg" alt="Sync API Tests"/></a>
    <a href="https://paypal.me/EchterAlsFake"><img src="https://img.shields.io/badge/Donate-PayPal-blue.svg?logo=paypal" alt="Donate via PayPal"/></a>
</div>

# Disclaimer
> [!IMPORTANT]
> This is an unofficial and unaffiliated project. Please read the full disclaimer before use:
> **[DISCLAIMER.md](https://github.com/EchterAlsFake/API_Docs/blob/master/Disclaimer.md)**
>
> By using this project you agree to comply with the target site’s rules, copyright/licensing requirements,
> and applicable laws. Do not use it to bypass access controls or scrape at disruptive rates.

# Features
- Insanely Fast (uses selectolax for parsing)
- Fully Asynchronous
- Mimics a real browser (using curl_cffi)
- Fetch videos + full metadata
- Download videos (supports HLS/m3u8 streams and raw MP4)
- Fetch Channels, Pornstars, Users, and Collections
- Search for videos with specific filters (duration, resolution, sorting)
- Custom concurrency controls (set limits for pages/videos)
- Built-in error handling with custom callbacks
- Built-in caching
- Easy object-oriented interface (e.g., async for video in channel.videos())
- Great type hinting (strict typing and memory-efficient dataclasses)

#### Networking Features
- HTTP 2.0 / HTTP 3.0
- Browser impersonation
- Custom JA3
- All proxy types
- Proxy authentication
- Speed Limit
- DNS over HTTPS
- And even more...
- All of this is configurable and can be adjusted as you like!

# Supported Platforms
This API has been tested and confirmed working on:

- Windows 11 (x64) 
- macOS Sequoia (x86_64)
- Linux (Arch) (x86_64)
- Android 16 (aarch64)

## Support the Project
> [!TIP]
> I am a student and I invest a massive amount of my free time into developing and maintaining this project under my real name. 
> If this library saves you time or helps you build something cool, a small donation makes a huge difference in my life! 
> Even 1€ is incredibly appreciated as a thank-you.

If you can't donate, please star the repository—it helps a lot!

- **PayPal**: https://paypal.me/EchterAlsFake
- **Monero**: 42XwGZYbSxpMvhn9eeP4DwMwZV91tQgAm3UQr6Zwb2wzBf5HcuZCHrsVxa4aV2jhP4gLHsWWELxSoNjfnkt4rMfDDwXy9jR

# Quickstart

### Have a look at the [Documentation](https://github.com/EchterAlsFake/API_Docs/blob/master/Porn_APIs/YouPorn.md) for more details
- Install the library with `pip install youporn_api`


```python
import asyncio
from youporn_api import Client

async def main():
    # Initialize a Client object
    client = Client()
    
    # Fetch a video
    video_object = await client.get_video("<insert_url_here>")
    
    # Information from Video objects
    print(video_object.title)
    print(video_object.rating)
    # Download the video
    
    await video_object.download(downloader="threaded", quality="best", path="your_output_path + filename")
asyncio.run(main())
# SEE DOCUMENTATION FOR MORE
```

# Contribution
Do you see any issues or having some feature requests? Simply open an Issue or talk
in the discussions.

Pull requests are also welcome.

# License
Licensed under the LGPLv3 License
<br>Copyright (C) 2025-2026 Johannes Habel
