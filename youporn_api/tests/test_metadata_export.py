import unittest

from youporn_api.api import Video


class MetadataExportTests(unittest.TestCase):
    def test_cast_labels_survive_extraction(self):
        source = Video(url="https://www.youporn.com/watch/123/example/", core=None)
        fields = source._extract_data('<h1 class="videoTitle">Example</h1><a class="metaDataPornstarLink tm_pornstar_link" href="/pornstar/example/">Example Actor</a>')
        self.assertEqual(fields["performers"], [{"name": "Example Actor", "url": "/pornstar/example/"}])
