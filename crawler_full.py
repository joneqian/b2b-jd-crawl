#!/usr/bin/env python3
"""
京东万商商品数据爬虫 - 完整版
包含自动登录和商品爬取功能
"""

import os
import json
import asyncio
import re
import sys
import signal
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from openpyxl import Workbook

# 加载环境变量
load_dotenv()

# 配置
BASE_URL = "https://b2b.jd.com"
LOGIN_URL = "https://b2b.jd.com/account/login"
TARGET_URL = "https://b2b.jd.com/index/jdgp-list"
COOKIES_FILE = "cookies.json"
OUTPUT_DIR = Path("output")
SCREENSHOTS_DIR = Path("screenshots")

# 爬取配置
# 支持多个类目，用逗号分隔，如: "休闲零食,饮料冲调,粮油调味"
CATEGORY_NAMES = [c.strip() for c in os.getenv("CATEGORY_NAMES", "休闲零食").split(",") if c.strip()]
START_PAGE = int(os.getenv("START_PAGE", "1"))
END_PAGE = int(os.getenv("END_PAGE", "3"))


class JDCrawler:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.products = []
        self.current_category = None  # 当前正在爬取的类目

    async def init(self, headless=True):
        """初始化浏览器"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=headless)
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.page = await self.context.new_page()

        # 应用stealth
        stealth = Stealth()
        await stealth.apply_stealth_async(self.page)

    async def load_cookies(self):
        """加载cookies"""
        if os.path.exists(COOKIES_FILE):
            with open(COOKIES_FILE, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            await self.context.add_cookies(cookies)
            print("✓ 已加载 Cookies")
            return True
        return False

    async def save_cookies(self):
        """保存cookies"""
        cookies = await self.context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print("✓ Cookies 已保存")

    async def handle_risk_verification(self):
        """处理风控验证"""
        current_url = self.page.url
        if "risk_handler" in current_url or "cfe.m.jd.com" in current_url:
            print("→ 检测到风控验证页面，请在浏览器中完成验证...")
            print("  （验证完成后页面会自动跳转）")

            for i in range(180):
                await self.page.wait_for_timeout(1000)
                current_url = self.page.url
                if "risk_handler" not in current_url and "cfe.m.jd.com" not in current_url:
                    print("✓ 验证通过！")
                    await self.save_cookies()
                    await self.page.wait_for_timeout(3000)
                    return True
                if i % 30 == 0 and i > 0:
                    print(f"  等待验证中... {i}秒")

            print("✗ 验证超时（3分钟）")
            return False
        return True

    async def wait_for_product_list_api(self, timeout=15000):
        """等待商品列表API响应完成"""
        api_responded = {"done": False}

        async def on_response(response):
            url = response.url
            if 'api.m.jd.com' in url:
                # 获取对应的请求，检查 POST 参数
                request = response.request
                post_data = request.post_data
                if post_data and 'functionId=bmall_goodsm_purchase_search_list' in post_data:
                    api_responded["done"] = True

        self.page.on('response', on_response)

        # 等待API响应，最多等待timeout毫秒
        wait_interval = 200
        max_wait = timeout // wait_interval
        for _ in range(max_wait):
            if api_responded["done"]:
                break
            await self.page.wait_for_timeout(wait_interval)

        self.page.remove_listener('response', on_response)

        if api_responded["done"]:
            # API已响应，额外等待一小段时间确保数据渲染完成
            await self.page.wait_for_timeout(1000)
            return True
        else:
            print(f"  ⚠ 等待商品列表API超时")
            return False

    async def select_type(self, type_name, timeout=10000):
        """选择商品类型（使用CSS选择器 + 文本匹配）"""
        try:
            # 使用 locator 查找：类型行 -> 包含指定文本的选项 -> 内部的 p 元素
            locator = self.page.locator('.shop-filter-item').filter(
                has_text='类型').locator(f'.content-item:has-text("{type_name}") p')

            # 等待元素出现
            await locator.wait_for(state='visible', timeout=timeout)
            await locator.click()
            print(f"  ✓ 已选择类型: {type_name}")
            return True

        except Exception as e:
            print(f"  ⚠ 选择类型失败: {e}")
            return False

    async def select_category(self, category_name, timeout=10000):
        """选择商品类目（使用CSS选择器 + 文本匹配）"""
        try:
            # 使用 locator 查找：类目行 -> 包含指定文本的选项 -> 内部的 p 元素
            locator = self.page.locator('.shop-filter-item').filter(
                has_text='类目').locator(f'.content-item:has-text("{category_name}") p')

            # 等待元素出现
            await locator.wait_for(state='visible', timeout=timeout)
            await locator.click()
            print(f"  ✓ 已选择类目: {category_name}")
            return True

        except Exception as e:
            print(f"  ⚠ 选择类目失败: {e}")
            return False

    async def check_login_status(self):
        """检查登录状态"""
        print(f"→ 检查登录状态...")
        await self.page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(5000)

        # 处理可能的风控验证
        if not await self.handle_risk_verification():
            return False

        current_url = self.page.url
        if "login" in current_url.lower():
            print("→ 未登录，需要登录")
            return False

        print("✓ 已登录")
        return True

    async def login(self):
        """执行登录"""
        username = os.getenv("JD_USERNAME")
        password = os.getenv("JD_PASSWORD")

        if not username or not password:
            print("✗ 错误: 请在 .env 文件中配置 JD_USERNAME 和 JD_PASSWORD")
            return False

        print(f"→ 正在登录，用户名: {username}")

        # 访问登录页
        await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await self.page.wait_for_timeout(3000)

        # 获取登录iframe
        login_frame = None
        for frame in self.page.frames:
            if "passport.jd.com/common/loginPage" in frame.url:
                login_frame = frame
                break

        if not login_frame:
            print("✗ 未找到登录iframe")
            SCREENSHOTS_DIR.mkdir(exist_ok=True)
            await self.page.screenshot(path=SCREENSHOTS_DIR / "login_error.png", full_page=True)
            return False

        print("✓ 找到登录iframe")

        # 等待表单元素
        await login_frame.wait_for_selector("#loginname", timeout=10000)
        await login_frame.wait_for_selector("#nloginpwd", timeout=10000)

        # 输入用户名
        await login_frame.fill("#loginname", "")
        await login_frame.type("#loginname", username, delay=100)
        print("✓ 已输入用户名")

        await self.page.wait_for_timeout(500)

        # 输入密码
        await login_frame.fill("#nloginpwd", "")
        await login_frame.type("#nloginpwd", password, delay=100)
        print("✓ 已输入密码")

        await self.page.wait_for_timeout(500)

        # 点击登录按钮
        print("→ 点击登录按钮...")
        try:
            await login_frame.evaluate('''() => {
                const btn = document.querySelector("#paipaiLoginSubmit");
                if (btn) {
                    const event = new MouseEvent('click', {
                        view: window,
                        bubbles: true,
                        cancelable: true
                    });
                    btn.dispatchEvent(event);
                }
            }''')
        except Exception as e:
            print(f"  登录按钮点击异常: {e}")

        await self.page.wait_for_timeout(3000)

        # 等待登录响应（最多2分钟）
        print("→ 等待登录响应...")
        for i in range(120):
            await self.page.wait_for_timeout(1000)
            current_url = self.page.url
            if "login" not in current_url.lower():
                print("✓ 登录成功！")
                await self.save_cookies()
                return True
            if i % 15 == 0 and i > 0:
                print(f"  已等待 {i} 秒...")

        # 超时提示手动登录
        print("→ 登录超时，请在浏览器中手动完成登录或验证")
        print("  完成后按 Enter 继续...")
        sys.stdin.readline()

        current_url = self.page.url
        if "login" not in current_url.lower():
            print("✓ 手动登录成功！")
            await self.save_cookies()
            return True
        else:
            print("✗ 登录失败")
            return False

    async def get_sku_ids_from_page(self, page_num, category_name=None):
        """从当前页面获取SKU ID列表（处理滚动懒加载）"""
        captured_skus = []

        async def capture_api(response):
            url = response.url
            if 'api.m.jd.com' in url:
                try:
                    body = await response.json()
                    if isinstance(body, dict):
                        data = body.get('data', {})
                        if isinstance(data, dict) and 'childList' in data:
                            for item in data['childList']:
                                if isinstance(item, dict) and 'skuId' in item:
                                    sku_id = str(item['skuId'])
                                    if sku_id not in captured_skus:
                                        captured_skus.append(sku_id)
                except:
                    pass

        self.page.on('response', capture_api)

        if page_num == 1:
            url = "https://b2b.jd.com/index/jdgp-list"
            print(f"→ 访问: {url}")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self.page.wait_for_timeout(3000)

            # 检查并处理风控验证
            if not await self.handle_risk_verification():
                self.page.remove_listener('response', capture_api)
                return []

            # 先选择类型为"自营"
            print(f"→ 选择类型: 自营")
            type_selected = await self.select_type("自营")
            if not type_selected:
                print(f"  ⚠ 未能选择'自营'类型")
            else:
                print(f"  → 等待商品列表加载...")
                await self.wait_for_product_list_api()

            # 清空之前捕获的SKU，只采集最终筛选后的商品
            captured_skus.clear()

            # 选择类目
            if category_name:
                print(f"→ 选择类目: {category_name}")
                category_selected = await self.select_category(category_name)
                if not category_selected:
                    print(f"  ⚠ 未找到类目 '{category_name}'，使用默认列表")
                else:
                    print(f"  → 等待商品列表加载...")
                    await self.wait_for_product_list_api()
        else:
            print(f"→ 切换到第 {page_num} 页")
            try:
                # 先滚动到底部找到分页控件
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self.page.wait_for_timeout(2000)

                # 尝试点击页码按钮
                clicked = False
                pager_selectors = [
                    f".rcd-pager__number:has-text('{page_num}')",
                    f"[class*='pager'] [class*='number']:has-text('{page_num}')",
                ]
                for selector in pager_selectors:
                    try:
                        btn = await self.page.query_selector(selector)
                        if btn:
                            await btn.click()
                            clicked = True
                            print(f"  点击页码成功")
                            break
                    except:
                        continue

                if not clicked:
                    # 尝试点击下一页
                    next_btn = await self.page.query_selector(".rcd-pagination__btn-next")
                    if next_btn:
                        await next_btn.click()
                        clicked = True
                        print(f"  点击下一页成功")

                # 翻页后回到顶部，准备滚动加载
                await self.page.wait_for_timeout(2000)
                await self.page.evaluate("window.scrollTo(0, 0)")
                await self.page.wait_for_timeout(1000)

            except Exception as e:
                print(f"  分页异常: {e}")

        # 滚动加载所有商品
        print(f"  → 滚动加载商品...")
        prev_count = 0
        no_new_count = 0
        max_scrolls = 20  # 最多滚动20次

        for scroll_i in range(max_scrolls):
            # 获取当前页面高度
            scroll_height = await self.page.evaluate("document.body.scrollHeight")
            viewport_height = await self.page.evaluate("window.innerHeight")

            # 分步滚动（每次滚动一个视口高度）
            current_scroll = await self.page.evaluate("window.pageYOffset")
            target_scroll = min(
                current_scroll + viewport_height, scroll_height)

            await self.page.evaluate(f"window.scrollTo(0, {target_scroll})")
            await self.page.wait_for_timeout(1500)  # 等待懒加载触发

            current_count = len(captured_skus)

            # 检查是否已滚动到底部且没有新商品
            at_bottom = target_scroll >= scroll_height - 100
            if current_count == prev_count:
                no_new_count += 1
                if at_bottom and no_new_count >= 2:
                    print(f"  → 已加载完成，共 {current_count} 个商品")
                    break
            else:
                no_new_count = 0
                print(f"    滚动 {scroll_i + 1}: 已捕获 {current_count} 个SKU")

            prev_count = current_count

        await self.page.wait_for_timeout(2000)
        self.page.remove_listener('response', capture_api)

        return captured_skus

    async def get_detail_from_api(self, sku_id):
        """获取商品详情"""
        detail_data = {}

        async def capture_detail_api(response):
            url = response.url
            if 'api.m.jd.com' in url:
                try:
                    body = await response.json()
                    if isinstance(body, dict):
                        result = body.get('result', {})
                        if isinstance(result, dict) and 'viewMasterMapDTO' in result:
                            detail_data['api_data'] = result
                except:
                    pass

        detail_page = await self.context.new_page()
        stealth = Stealth()
        await stealth.apply_stealth_async(detail_page)

        detail_page.on('response', capture_detail_api)

        detail_url = f"https://b2b.jd.com/goods/goods-detail/{sku_id}"

        try:
            await detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
            await detail_page.wait_for_timeout(8000)

            # 滚动触发懒加载
            for _ in range(3):
                await detail_page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
                await detail_page.wait_for_timeout(1000)
                await detail_page.evaluate("window.scrollTo(0, document.body.scrollHeight * 2 / 3)")
                await detail_page.wait_for_timeout(1000)
                await detail_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await detail_page.wait_for_timeout(1000)

            # 从HTML提取详情图
            if detail_data.get('api_data'):
                graphic_dto = detail_data['api_data'].get(
                    'viewGraphicDetailDTO', {})
                if not graphic_dto.get('productDesc'):
                    detail_images = await self._extract_detail_images(detail_page)
                    if detail_images:
                        detail_data['html_detail_images'] = detail_images

        except Exception as e:
            print(f"    ✗ 访问失败: {e}")
        finally:
            await detail_page.close()

        return detail_data

    async def _extract_detail_images(self, page):
        """从HTML提取详情图"""
        detail_images = []
        try:
            selectors = [".goodsdetail-content__image img",
                         "[class*='detail'] img"]
            for selector in selectors:
                imgs = await page.query_selector_all(selector)
                for img in imgs:
                    src = await img.get_attribute('src')
                    if src:
                        if src.startswith('//'):
                            src = 'https:' + src
                        if '360buyimg' in src and src not in detail_images:
                            src = src.split('!')[0].replace('/n4/', '/n1/')
                            detail_images.append(src)
        except:
            pass
        return detail_images

    def extract_product_info(self, api_data, html_detail_images=None):
        """提取商品信息"""
        info = {
            "sku_id": "",
            "name": "",
            "brand": "",
            "main_images": [],
            "params": {},
            "detail_images": [],
            "category": "",
            "shelf_life": "",
            "manufacturing_date": "",
            "jd_price": "",
            "retail_price": "",
            "main_price": "",
            "minimum_purchase": 9999,  # 起购数量，默认9999
        }

        if not api_data:
            return info

        # 标题
        title_dto = api_data.get('viewTitleDTO', {})
        info['name'] = title_dto.get('title', '')

        # 品牌
        brand_dto = api_data.get('viewBrandDTO', {})
        info['brand'] = brand_dto.get('brandName', '')
        if not info['brand']:
            common_dto = api_data.get('viewCommonDTO', {})
            info['brand'] = common_dto.get('brandName', '')

        # 通用信息
        common_dto = api_data.get('viewCommonDTO', {})
        info['sku_id'] = str(common_dto.get('skuId', ''))
        info['shelf_life'] = common_dto.get('shelfLife', '')
        info['manufacturing_date'] = common_dto.get('manufacturingDate', '')
        cat1 = common_dto.get('category_name1', '')
        cat2 = common_dto.get('category_name2', '')
        info['category'] = f"{cat1} > {cat2}" if cat1 and cat2 else cat1 or cat2

        # 价格
        price_dto = api_data.get('viewPriceDTO', {})
        price_info = price_dto.get('priceInfo', {})
        if isinstance(price_info, dict):
            jprice = price_info.get('jprice', {})
            if isinstance(jprice, dict):
                info['jd_price'] = jprice.get('value', '')
            main_jd_price = price_info.get('mainJdPrice', {})
            if isinstance(main_jd_price, dict):
                info['retail_price'] = main_jd_price.get('value', '')

        main_position_price = price_dto.get('mainPositionPrice', {})
        if isinstance(main_position_price, dict):
            info['main_price'] = main_position_price.get('value', '')

        # 起购数量
        selected_dto = api_data.get('viewSelectedDTO', {})
        if isinstance(selected_dto, dict):
            minimum_purchase = selected_dto.get('minimumPurchaseLimit')
            if minimum_purchase is not None:
                info['minimum_purchase'] = minimum_purchase

        # 主图
        master_dto = api_data.get('viewMasterMapDTO', {})
        for img in master_dto.get('wareImage', []):
            if isinstance(img, dict):
                big_url = img.get('big', '')
                if big_url and big_url not in info['main_images']:
                    info['main_images'].append(big_url)

        # 规格参数
        graphic_dto = api_data.get('viewGraphicDetailDTO', {})
        spec = graphic_dto.get('specification', {})
        if isinstance(spec, dict):
            for item in spec.get('specificationDetailList', []):
                if isinstance(item, dict):
                    name = item.get('attributeName', '')
                    value = item.get('attributes', '')
                    if name and value:
                        info['params'][name] = value

            for group in spec.get('specificationList', []):
                if isinstance(group, dict):
                    for attr in group.get('AttributeList', []):
                        if isinstance(attr, dict):
                            name = attr.get('attributeName', '')
                            value = attr.get('attributes', '')
                            if name and value and name not in info['params']:
                                info['params'][name] = value

        # 详情图
        product_desc = graphic_dto.get('productDesc', '')
        if product_desc:
            img_urls = re.findall(
                r'(?:src|data-lazyload)=["\']([^"\'\s]+)["\']', product_desc)
            for img_url in img_urls:
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                if '360buyimg' in img_url and img_url not in info['detail_images']:
                    info['detail_images'].append(img_url)

        if not info['detail_images'] and html_detail_images:
            info['detail_images'] = html_detail_images

        return info

    async def crawl_category(self, category_name):
        """爬取单个类目的商品"""
        print(f"\n{'=' * 60}")
        print(f"开始爬取类目: {category_name}")
        print(f"页码范围: {START_PAGE} - {END_PAGE}")
        print("=" * 60)

        # 记录当前类目，清空上一个类目的数据
        self.current_category = category_name
        self.products = []
        all_sku_ids = []

        # 获取商品列表
        for page_num in range(START_PAGE, END_PAGE + 1):
            print(f"\n=== 第 {page_num} 页 ===")
            sku_ids = await self.get_sku_ids_from_page(page_num, category_name)
            print(f"  获取到 {len(sku_ids)} 个SKU")

            for sku_id in sku_ids:
                if sku_id not in all_sku_ids:
                    all_sku_ids.append(sku_id)

            await self.page.wait_for_timeout(2000)

        print(f"\n✓ 类目 [{category_name}] 共获取 {len(all_sku_ids)} 个商品SKU")

        # 获取商品详情
        print(f"\n=== 开始获取商品详情 ===")

        for i, sku_id in enumerate(all_sku_ids):
            print(f"\n[{i+1}/{len(all_sku_ids)}] 处理商品 {sku_id}")
            print(f"  → 访问详情页")

            detail_result = await self.get_detail_from_api(sku_id)
            api_data = detail_result.get('api_data', {})
            html_images = detail_result.get('html_detail_images', [])

            if api_data:
                product_info = self.extract_product_info(api_data, html_images)
                if not product_info['sku_id']:
                    product_info['sku_id'] = sku_id
                self.products.append(product_info)
                print(f"    ✓ {product_info['name'][:40]}...")
                print(f"      品牌: {product_info['brand']}")
                print(
                    f"      京东价: ¥{product_info['jd_price']}  建议零售价: ¥{product_info['retail_price']}")
                print(
                    f"      主图: {len(product_info['main_images'])} 张, 详情图: {len(product_info['detail_images'])} 张")
            else:
                print(f"    ✗ 未获取到数据")
                self.products.append({'sku_id': sku_id})

            await asyncio.sleep(1)

        print(f"\n✓ 类目 [{category_name}] 共处理 {len(self.products)} 个商品")

        # 保存当前类目的数据
        if self.products:
            await self.save_to_excel(category_name)

    async def crawl(self):
        """执行爬取（支持多个类目）"""
        print("=" * 60)
        print("京东万商商品数据爬虫")
        print(f"类目列表: {', '.join(CATEGORY_NAMES)}")
        print(f"页码范围: {START_PAGE} - {END_PAGE}")
        print("=" * 60)

        # 初始化浏览器（有头模式以便处理验证）
        await self.init(headless=False)

        # 尝试加载cookies
        await self.load_cookies()

        # 检查登录状态
        is_logged_in = await self.check_login_status()

        if not is_logged_in:
            # 执行登录
            login_success = await self.login()
            if not login_success:
                print("✗ 登录失败，退出")
                await self.close()
                return

        # 显示浏览器窗口进行爬取（方便调试）
        await self.close()
        await self.init(headless=False)
        await self.load_cookies()

        # 依次爬取每个类目
        for i, category_name in enumerate(CATEGORY_NAMES):
            print(f"\n{'#' * 60}")
            print(f"# 进度: {i+1}/{len(CATEGORY_NAMES)} - 类目: {category_name}")
            print("#" * 60)

            await self.crawl_category(category_name)

        print(f"\n{'=' * 60}")
        print(f"全部类目爬取完成！共 {len(CATEGORY_NAMES)} 个类目")
        print("=" * 60)

    async def save_to_excel(self, category_name="未分类"):
        """保存到Excel"""
        OUTPUT_DIR.mkdir(exist_ok=True)

        wb = Workbook()
        ws = wb.active
        ws.title = "商品详情"

        headers = [
            "SKU ID", "商品名称", "品牌", "分类",
            "京东价", "建议零售价", "主显示价", "起购数量",
            "保质期", "生产日期",
            "主图1", "主图2", "主图3", "主图4", "主图5",
            "参数JSON", "详情图数量", "详情图列表"
        ]
        ws.append(headers)

        for product in self.products:
            main_images = product.get("main_images", [])
            main_images = main_images[:5] + [''] * (5 - len(main_images[:5]))
            detail_images = product.get("detail_images", [])

            row = [
                product.get("sku_id", ""),
                product.get("name", ""),
                product.get("brand", ""),
                product.get("category", ""),
                product.get("jd_price", ""),
                product.get("retail_price", ""),
                product.get("main_price", ""),
                product.get("minimum_purchase", 9999),
                product.get("shelf_life", ""),
                product.get("manufacturing_date", ""),
                main_images[0], main_images[1], main_images[2], main_images[3], main_images[4],
                json.dumps(product.get("params", {}), ensure_ascii=False),
                len(detail_images),
                "; ".join(detail_images[:10]),
            ]
            ws.append(row)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = OUTPUT_DIR / f"products_{category_name}_{timestamp}.xlsx"
        wb.save(filename)
        print(f"\n✓ Excel已保存: {filename}")

        json_filename = OUTPUT_DIR / f"products_{category_name}_{timestamp}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(self.products, f, ensure_ascii=False, indent=2)
        print(f"✓ JSON已保存: {json_filename}")

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


async def main():
    crawler = JDCrawler()
    interrupted = False

    def signal_handler(signum, frame):
        nonlocal interrupted
        interrupted = True
        print("\n\n⚠ 收到退出信号，正在保存已爬取的数据...")

    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await crawler.crawl()
    except KeyboardInterrupt:
        interrupted = True
        print("\n\n⚠ 用户中断，正在保存已爬取的数据...")
    except Exception as e:
        interrupted = True
        print(f"\n\n✗ 爬虫异常: {e}")
        print("→ 正在保存已爬取的数据...")
    finally:
        # 无论正常结束还是异常退出，都尝试保存未保存的数据
        if interrupted and crawler.products:
            category_name = crawler.current_category or "未知类目"
            print(f"\n→ 类目 [{category_name}] 已爬取 {len(crawler.products)} 个商品，正在导出...")
            try:
                await crawler.save_to_excel(category_name)
            except Exception as e:
                print(f"✗ 导出失败: {e}")
                # 尝试保存为 JSON 作为最后的兜底
                try:
                    emergency_file = OUTPUT_DIR / \
                        f"emergency_backup_{category_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                    OUTPUT_DIR.mkdir(exist_ok=True)
                    with open(emergency_file, "w", encoding="utf-8") as f:
                        json.dump(crawler.products, f,
                                  ensure_ascii=False, indent=2)
                    print(f"✓ 紧急备份已保存: {emergency_file}")
                except:
                    pass
        elif interrupted:
            print("→ 没有已爬取的数据需要保存")

        await crawler.close()


if __name__ == "__main__":
    asyncio.run(main())
