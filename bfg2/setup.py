from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='bfg2',
    version='0.1.0',
    author='Surlex Limited',
    author_email='mark@surlex.com',
    description='Business Foundation Generator - Django library for websites and e-commerce',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/yinxiangming/bfg2',
    packages=find_packages(),
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Framework :: Django',
        'Framework :: Django :: 5.0',
    ],
    python_requires='>=3.11',
    install_requires=[
        'Django>=5.0,<6.0',
        'djangorestframework>=3.14',
        'django-allauth>=0.57',
        'Pillow>=10.0',
        'django-cors-headers>=4.3',
        'celery>=5.3',
        'redis>=5.0',
        'mysqlclient>=2.2',
    ],
    extras_require={
        'dev': [
            'pytest>=7.4',
            'pytest-django>=4.5',
            'black>=23.0',
            'flake8>=6.0',
            'mypy>=1.5',
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
