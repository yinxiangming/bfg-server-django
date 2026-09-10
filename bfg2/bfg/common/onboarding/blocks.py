# -*- coding: utf-8 -*-
"""Block layouts the wizard (and ``provision_workspace``) publish pages with."""


def home_page_blocks():
    """The block list a storefront home page needs to show anything.

    ``source: "promo"`` resolves against the workspace's home Campaign at render
    time and ``source: "auto"`` against the storefront product API, so the same
    blocks work for a workspace with no content yet — the rails just render their
    empty message until products are flagged.
    """

    def product_grid(block_id, product_type, title_en, title_zh, empty_en, empty_zh, alt=False):
        return {
            'id': block_id,
            'type': 'product_grid_v1',
            'settings': {'columns': 4, 'limit': 8, 'showTitle': True, 'altBackground': alt},
            'data': {
                'source': 'auto',
                'productType': product_type,
                'title': {'en': title_en, 'zh-hans': title_zh},
                'emptyMessage': {'en': empty_en, 'zh-hans': empty_zh},
            },
        }

    return [
        {
            'id': 'hero-carousel',
            'type': 'hero_carousel_v1',
            'settings': {'autoPlay': True, 'interval': 5000, 'showArrows': True,
                         'showDots': True, 'height': '500px'},
            'data': {'source': 'promo', 'slides': []},
        },
        {
            'id': 'content-section',
            'type': 'section_v1',
            'settings': {},
            'data': {
                'width': 'container',
                'children': [
                    {
                        'id': 'category-grid',
                        'type': 'category_grid_v1',
                        'settings': {'columns': 4, 'limit': 12, 'showCount': True,
                                     'imageHeight': '180px'},
                        'data': {'source': 'promo'},
                    },
                    product_grid('featured-products', 'featured', 'Featured', '精选商品',
                                 'No featured products yet.', '暂无精选商品。', alt=True),
                    product_grid('new-products', 'new', 'New Arrivals', '新品上架',
                                 'No new products yet.', '暂无新品。'),
                    product_grid('bestseller-products', 'bestseller', 'Bestsellers', '畅销榜',
                                 'No bestsellers yet.', '暂无畅销商品。', alt=True),
                ],
            },
        },
    ]
