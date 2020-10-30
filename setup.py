from setuptools import setup


setup(
    name="probostitcher",
    version="0.1",
    description="Combine video files using a JSON file as directions",
    author="Silvio Tomatis",
    author_email="silviot@gmail.com",
    license="GPLv3+",
    install_requires=["ffmpeg-python", "pendulum"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)",
        "Operating System :: POSIX",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Video :: Conversion",
        "Topic :: Multimedia :: Video :: Non-Linear Editor",
    ],
    entry_points={
        "console_scripts": [
            "probostitcher = probostitcher.server:main",
            "probostitcher-worker = probostitcher.worker:main",
        ],
    },
    packages=["probostitcher"],
    zip_safe=False,
)
