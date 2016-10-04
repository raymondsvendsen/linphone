#!/usr/bin/python


import pystache
import re
import genapixml as CApi
import abstractapi as AbsApi


class CppTranslator(object):
	def translate_enum(self, enum):
		enumDict = {}
		enumDict['name'] = enum.name.translate(self)
		enumDict['values'] = []
		i = 0
		for enumValue in enum.values:
			enumValDict = enumValue.translate(self)
			enumValDict['notLast'] = (i != len(enum.values)-1)
			enumDict['values'].append(enumValDict)
			i += 1
		return enumDict
	
	def translate_enum_value(self, enumValue):
		enumValueDict = {}
		enumValueDict['name'] = enumValue.name.translate(self)
		return enumValueDict
	
	def translate_class(self, _class):
		classDict = {}
		classDict['name'] = _class.name.translate(self)
		classDict['methods'] = []
		classDict['staticMethods'] = []
		for method in _class.instanceMethods:
			methodDict = self.translate_method(method)
			classDict['methods'].append(methodDict)
		for method in _class.classMethods:
			methodDict = self.translate_method(method)
			classDict['staticMethods'].append(methodDict)
		return classDict
	
	def translate_method(self, method):
		try:
			returnType = 'void' if method.returnType is None else method.returnType.translate(self)
		except RuntimeError as e:
			print('Cannot translate the return type of {0}: {1}'.format(method.name.format_as_c() + '()', e.args[0]))
			returnType = None
		
		methodName = method.name.translate(self)
		if methodName == 'new':
			methodName = '_new'
		methodDict = {}
		methodDict['prototype'] = '{0} {1}();'.format(returnType, methodName)
		if method.type == AbsApi.Method.Type.Class:
			methodDict['prototype'] = 'static ' + methodDict['prototype'];
		return methodDict
	
	def translate_base_type(self, type):
		if type.name == 'boolean':
			res = 'bool'
		elif type.name == 'character':
			res = 'char'
		elif type.name == 'integer':
			if type.size is None:
				res = 'int'
			elif isinstance(type.size, str):
				res = type.size
			else:
				res = 'int{0}_t'.format(type.size)
		elif type.name == 'floatant':
			if type.size is not None and type.size == 'double':
				res = 'double'
			else:
				res = 'float'
		elif type.name == 'string':
			res = 'std::string'
		else:
			raise RuntimeError('\'{0}\' is not a base abstract type'.format(type.name))
		
		if type.isUnsigned:
			if type.name == 'integer' and isinstance(type.size, int):
				res = 'u' + res
			else:
				res = 'unsigned ' + res
		if type.isconst:
			res = 'const ' + res
		if type.isref:
			res += ' &'
		return res
	
	def translate_enum_type(self, type):
		if type.desc is None:
			raise RuntimeError('{0} has not been fixed'.format(type))
		
		commonParentName = AbsApi.Name.find_common_parent(type.desc.name, type.parent.name)
		return self.translate_relative_name(type.desc.name, commonParentName)
	
	def translate_class_type(self, type):
		if type.desc is None:
			raise RuntimeError('{0} has not been fixed'.format(type))
		
		commonParentName = AbsApi.Name.find_common_parent(type.desc.name, type.parent.name)
		res = self.translate_relative_name(type.desc.name, commonParentName)
		if type.isconst:
			res = 'const ' + res
		return 'std::shared_ptr<{0}>'.format(res)
	
	def translate_list_type(self, type):
		if type.containedTypeDesc is None:
			raise RuntimeError('{0} has not been fixed'.format(type))
		elif isinstance(type.containedTypeDesc, AbsApi.BaseType):
			res = self.translate_base_type(type.containedTypeDesc)
		else:
			commonParentName = AbsApi.Name.find_common_parent(type.containedTypeDesc.desc.name, type.parent.name)
			res = self.translate_relative_name(type.containedTypeDesc.desc.name, commonParentName)
		return 'std::list<std::shared_ptr<{0}> >'.format(res)
	
	def translate_full_name(self, name):
		if name.prev is None:
			return name.translate(self)
		else:
			return self.translate_full_name(name.prev) + '::' + name.translate(self)
	
	def translate_relative_name(self, name, prefix):
		copy = name.copy()
		copy.delete_prefix(prefix)
		return self.translate_full_name(copy)
	
	def translate_class_name(self, name):
		res = ''
		for word in name.words:
			res += word.title()
		return res
	
	def translate_enum_name(self, name):
		return CppTranslator.translate_class_name(self, name)
	
	def translate_enum_value_name(self, name):
		return CppTranslator.translate_class_name(self, name)
	
	def translate_method_name(self, name):
		res = ''
		first = True
		for word in name.words:
			if first:
				first = False
				res += word
			else:
				res += word.title()
		return res
	
	def translate_namespace_name(self, name):
		return ''.join(name.words)


class EnumsHeader(object):
	def __init__(self, translator):
		self.translator = translator
		self.enums = []
	
	def add_enum(self, enum):
		self.enums.append(enum.translate(self.translator))


class ClassHeader(object):
	def __init__(self, _class, translator):
		self._class = _class.translate(translator)
		self.define = ClassHeader._class_name_to_define(_class.name)
		self.filename = ClassHeader._class_name_to_filename(_class.name)
		self.includes = {'internal': [], 'external': []}
		self.update_includes(_class)
	
	def update_includes(self, _class):
		includes = {'internal': set(), 'external': set()}
		for method in (_class.classMethods + _class.instanceMethods):
			retIncludes = self._needed_includes_from_type(method.returnType, _class)
			includes['internal'] |= retIncludes['internal']
			includes['external'] |= retIncludes['external']
		
		self.internalIncludes = []
		self.externalIncludes = []
		for include in includes['internal']:
			self.includes['internal'].append({'name': include})
		for include in includes['external']:
			self.includes['external'].append({'name': include})
	
	def _needed_includes_from_type(self, type, currentClass):
		res = {'internal': set(), 'external': set()}
		if isinstance(type, AbsApi.ClassType):
			res['external'].add('memory')
			if type.desc is not None and type.desc is not currentClass:
				res['internal'].add('_'.join(type.desc.name.words))
		elif isinstance(type, AbsApi.EnumType):
			res['internal'].add('enums')
		elif isinstance(type, AbsApi.BaseType):
			if type.name == 'integer' and isinstance(type.size, int):
				res['external'].add('cstdint')
			elif type.name == 'string':
				res['external'].add('string')
		elif isinstance(type, AbsApi.ListType):
			res['external'].add('list')
			retIncludes = self._needed_includes_from_type(type.containedType, currentClass)
			res['external'] |= retIncludes['external']
			res['internal'] = retIncludes['internal']
		return res
	
	@staticmethod
	def _class_name_to_define(className):
		words = className.words
		res = ''
		for word in words:
			res += ('_' + word.upper())
		res += '_HH'
		return res

	@staticmethod
	def _class_name_to_filename(className):
		words = className.words
		res = ''
		first = True
		for word in words:
			if first:
				first = False
			else:
				res += '_'
			res += word.lower()
		
		res += '.hh'
		return res


def main():
	project = CApi.Project()
	project.initFromDir('../../work/coreapi/help/doc/xml')
	project.check()
	
	translator = CppTranslator()
	parser = AbsApi.CParser(project)
	parser.parse_all()
	renderer = pystache.Renderer()	
	
	header = EnumsHeader(translator)
	for enum in parser.enumsIndex.itervalues():
		header.add_enum(enum)
	
	with open('include/enums.hh', mode='w') as f:
		f.write(renderer.render(header))
	
	for _class in parser.classesIndex.itervalues():
		if _class is not None:
			header = ClassHeader(_class, translator)
			with open('include/' + header.filename, mode='w') as f:
				f.write(renderer.render(header))


if __name__ == '__main__':
	main()