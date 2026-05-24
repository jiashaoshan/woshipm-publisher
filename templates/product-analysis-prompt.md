你是一个产品分析专家。以下是一个产品页面的实际抓取内容，请分析并提取结构化信息。

产品链接: {{product_url}}

## 页面内容
{{page_content}}

## 要求
请根据以上页面内容（而不是根据你的常识）提取结构化信息。

返回 JSON:
{
  "product_name": "产品名称",
  "tagline": "一句话卖点（15字以内）",
  "target_audience": "目标用户群体",
  "core_features": ["核心功能1", "核心功能2", "核心功能3"],
  "pain_points_solved": ["解决的痛点1", "解决的痛点2"],
  "user_value": "给用户带来的核心价值（50字内）",
  "differentiators": ["与竞品差异点1", "差异点2"],
  "tech_stack": "技术栈/技术背景（如有）"
}
